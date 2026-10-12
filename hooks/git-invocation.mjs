// Shared git-invocation analyzer for the command guards (scan-commit.mjs, branch-guard.mjs).
//
// WHY THIS EXISTS
// Both guards used to gate their entire logic on a raw substring test:
//     if (!/\bgit\b[\s\S]*\bcommit\b/.test(cmd)) process.exit(0);
// A git ALIAS performs a real commit with that substring absent. `git config alias.ci 'commit -a'`
// then `git ci -m x` commits (including `-a`, which sweeps unstaged changes) while the guard sees
// no "commit" and skips every check. Setting the alias matched neither guard either, so one
// unguarded `git config` call silently disarmed both controls for the rest of the session.
// Verified against real git: alias chains resolve (deep -> ci -> commit), `-c alias.x=y` works
// inline, and `git config --get alias.<name>` reads the same table git itself uses.
//
// WHAT THIS CAN AND CANNOT SEE (honest coverage — read before trusting it)
// Resolvable here, because git resolves them itself from config we can read:
//   * `git config alias.*`, including chains and `!shell` aliases
//   * `-c alias.x=y` inline config, global options (`-C`, `--no-pager`, `--git-dir=`), wrappers
//     (`sudo`, `env`, `command`, `timeout`, ...), and quoted command names (`"git"`, g'i't)
// NOT resolvable at this layer, by construction:
//   * SHELL aliases and functions from ~/.bashrc / ~/.zshrc. Claude Code sources the user's shell
//     startup file and applies those aliases to every Bash command AFTER the hook has decided, so
//     `alias gc='git commit'` + `gc` reaches us as the string "gc" with nothing to resolve.
//   * $PATH shadowing, `eval`, variable indirection (`C=commit; git $C`), base64-decode-pipe-to-sh.
// Those need enforcement below the alias layer (a repo `pre-commit` hook, or a state-based scan of
// what actually landed). This module makes the PreToolUse gate correct for everything git itself
// resolves; it does not make a pre-execution string gate authoritative, which is impossible.

import { runGit } from './git-exec.mjs';
import { resolve as resolvePath } from 'node:path';
import { skipCommandPrefix } from './shell-prefix.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';

// Wrappers whose real command follows them (mirrors destructive-command-guard.mjs).
// positional = positional args the wrapper itself consumes before the real command.
const WRAPPERS = {
  sudo: { positional: 0, argOpts: ['-u', '-g', '-p'] },
  env: { positional: 0, argOpts: [] },
  command: { positional: 0, argOpts: [] },
  builtin: { positional: 0, argOpts: [] },
  nohup: { positional: 0, argOpts: [] },
  setsid: { positional: 0, argOpts: [] },
  time: { positional: 0, argOpts: ['-o', '--output', '-f', '--format'] },
  stdbuf: { positional: 0, argOpts: ['-i', '-o', '-e'] },
  timeout: { positional: 1, argOpts: ['-s', '--signal', '-k'] },
  nice: { positional: 0, argOpts: ['-n', '--adjustment'] },
  ionice: { positional: 0, argOpts: ['-c', '-n', '-p'] },
  xargs: { positional: 0, argOpts: ['-I', '-n', '-P', '-d'] },
};

// Names git resolves as real commands. git DOES NOT honour an alias that hides an existing git
// command -- verified: with `alias.status = "commit -a"` set, `git status` still runs status. So a
// builtin name must never be expanded, or `git status` in a repo carrying that alias would be
// treated as a commit and scanned (a false positive that could DENY a read-only command). Skipping
// them also removes the `git config` subprocess from the common path entirely.
const GIT_BUILTINS = new Set([
  'add', 'am', 'annotate', 'apply', 'archive', 'bisect', 'blame', 'branch', 'bundle', 'cat-file',
  'check-ignore', 'checkout', 'cherry', 'cherry-pick', 'clean', 'clone', 'commit', 'config',
  'describe', 'diff', 'difftool', 'fetch', 'for-each-ref', 'format-patch', 'fsck', 'gc', 'grep',
  'help', 'init', 'log', 'ls-files', 'ls-remote', 'ls-tree', 'merge', 'mergetool', 'mv', 'notes',
  'pull', 'push', 'range-diff', 'rebase', 'reflog', 'remote', 'repack', 'replace', 'reset',
  'restore', 'rev-list', 'rev-parse', 'revert', 'rm', 'shortlog', 'show', 'show-ref', 'sparse-checkout',
  'stash', 'status', 'submodule', 'switch', 'symbolic-ref', 'tag', 'update-index', 'update-ref',
  'version', 'whatchanged', 'worktree', 'write-tree',
]);

// git global options that take a SEPARATE value argument, so the value is not the subcommand.
const GIT_GLOBAL_VALUE_OPTS = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env']);

// Quote-aware tokenizer: splits on unquoted whitespace and removes quote delimiters, so
// `"git" commit`, `g'i't commit` and `git   commit` all tokenize to ["git", "commit"].
// Single pass, no backtracking.
export function tokenize(text) {
  // Decode `$'...'` first: bash substitutes those escapes before git sees them, so a message
  // written as $'\\x73\\x6b...' really lands in history as `sk-...`. Reading the raw token made
  // the scanner blind to it.
  text = expandAnsiCQuotes(text);
  const out = [];
  let cur = '';
  let has = false;
  let q = null;
  const s = String(text ?? '');
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    if (q) {
      if (c === q) { q = null; continue; }
      cur += c; has = true; continue;
    }
    if (c === '\\' && i + 1 < s.length) { cur += s[i + 1]; has = true; i += 1; continue; }
    if (c === "'" || c === '"') { q = c; has = true; continue; }
    if (/\s/.test(c)) { if (has) { out.push(cur); cur = ''; has = false; } continue; }
    cur += c; has = true;
  }
  if (has) out.push(cur);
  return out;
}

// Quote-aware split on statement separators, so each segment is one command.
// True when an `&` belongs to a redirect operator rather than separating two statements:
// `2>&1`, `<&0`, `&>log`, `&>>log`.
//
// Takes the last non-space character of the current segment and whether it was ESCAPED,
// rather than the segment itself. An earlier version scanned backward over the segment; the
// loop body was O(1), but indexing a string built by `+=` forces V8 to flatten the ConsString
// rope that `+=` then rebuilds, so a shape where every `&` runs this check was quadratic -
// 13.6 s at 512 KB, past the wired hook budget, where a killed hook renders no decision.
//
// An escaped `>` is literal text, not an operator: without that distinction
// `echo a\> & git commit ...` read as a redirect, the `&` stopped separating, and the commit
// after it was never resolved.
function ampersandIsRedirect(next, lastNonSpace, lastWasEscaped) {
  if (next === '>') return true;
  if (lastNonSpace !== '>' && lastNonSpace !== '<') return false;
  return !lastWasEscaped;
}

export function splitStatements(text) {
  const segs = [];
  let cur = '';
  let q = null;
  const s = String(text ?? '');
  // Carried alongside `cur` so the redirect test never has to index it. `lastNonSpace` is the
  // last non-blank character appended to the current segment, `lastWasEscaped` says whether
  // an odd run of backslashes preceded it, and `backslashRun` counts the run in progress.
  let lastNonSpace = '';
  let lastWasEscaped = false;
  let backslashRun = 0;
  const keep = (ch) => {
    cur += ch;
    if (ch !== ' ' && ch !== '\t') {
      lastNonSpace = ch;
      lastWasEscaped = backslashRun % 2 === 1;
    }
    backslashRun = ch === '\\' ? backslashRun + 1 : 0;
  };
  const flush = () => {
    segs.push(cur);
    cur = '';
    lastNonSpace = '';
    lastWasEscaped = false;
    backslashRun = 0;
  };
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    const n = s[i + 1];
    if (q) { keep(c); if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; keep(c); continue; }
    if (c === ';' || c === '\n') { flush(); continue; }
    if ((c === '&' || c === '|') && n === c) { flush(); i += 1; continue; }
    // A bare `&` is a separator EXCEPT inside a redirect operator (`2>&1`, `<&0`, `&>log`).
    // Splitting there left a fragment starting with a bare fd digit, so the command after it
    // was never resolved.
    if (c === '&' && ampersandIsRedirect(n, lastNonSpace, lastWasEscaped)) { keep(c); continue; }
    if (c === '|' || c === '&') { flush(); continue; }
    keep(c);
  }
  if (cur) segs.push(cur);
  return segs;
}

// Strip wrapping subshell `( ... )` / brace-group `{ ...; }` delimiters. Without this the first
// token of `(git commit -am x)` is `(git`, whose basename is not `git`, so the whole statement was
// invisible to the resolver and BOTH guards exited — a plain, everyday shell construct defeating
// them completely. destructive-command-guard.mjs has stripped these for a long time; this resolver
// simply never re-asked the question. LINEAR single-char slices, deliberately not a regex with a
// greedy quantifier before an anchor (see lessons.md).
function stripGroupWrappers(seg) {
  let s = String(seg).trim();
  for (let i = 0; i < 8; i += 1) {
    const before = s;
    if (s.startsWith('(') || s.startsWith('{')) s = s.slice(1).trim();
    if (s.endsWith(')') || s.endsWith('}')) s = s.slice(0, -1).trim();
    if (s === before) break;
  }
  return s;
}

function basename(token) {
  const t = String(token).replace(/\\/g, '/');
  const i = t.lastIndexOf('/');
  return i === -1 ? t : t.slice(i + 1);
}

// Strip leading `VAR=value` assignments and known wrappers to reach the real command.
function unwrap(tokens) {
  // The prefix grammar and the wrapper table ALTERNATE to a fixed point: `then env FOO=1
  // nohup git commit` is prefix, wrapper, prefix, wrapper. `skipCommandPrefix` is shared with
  // destructive-command-guard.mjs so the two resolvers cannot diverge on the construct set
  // again - they walked off different subsets before, and every bypass that produced was the
  // same failure: the first token was a prefix construct, so the real command was never seen.
  // Index walk rather than repeated slicing: the old version rebuilt the array at every step,
  // which is quadratic on a long statement and reachable from agent-influenced input.
  let i = 0;
  for (let guard = 0; guard < 10 && i < tokens.length; guard += 1) {
    i = skipCommandPrefix(tokens, i);
    if (i >= tokens.length) return [];
    const name = basename(tokens[i]).toLowerCase().replace(/\.exe$/, '');
    const w = WRAPPERS[name];
    if (!w) return tokens.slice(i);
    i += 1;
    // OPTIONS FIRST, then the positional. The other order mis-parses `timeout -k 1 2 <cmd>`:
    // `-k` takes `1`, and `2` is the duration. Consuming the positional first ate `1` and
    // left `2` where the command name should be.
    while (i < tokens.length && tokens[i].startsWith('-')) {
      const opt = tokens[i];
      i += 1;
      if (w.argOpts.includes(opt) && i < tokens.length) i += 1;
    }
    for (let p = 0; p < w.positional && i < tokens.length; p += 1) {
      if (tokens[i].startsWith('-')) break;
      i += 1;
    }
  }
  return tokens.slice(i);
}

// Given the tokens of ONE command, return { subcommand, args, inlineAliases } if it invokes git.
function gitCall(tokens) {
  const t = unwrap(tokens);
  if (!t.length) return null;
  const name = basename(t[0]).toLowerCase().replace(/\.exe$/, '');
  if (name !== 'git') return null;
  const inlineAliases = new Map();
  const dirs = [];
  let i = 1;
  while (i < t.length) {
    const a = t[i];
    if (!a.startsWith('-')) break;
    // `-c alias.ci=commit` and `-c=` / `--git-dir=...` inline forms.
    const eq = a.indexOf('=');
    if (a === '-c' && i + 1 < t.length) {
      const kv = t[i + 1];
      const j = kv.indexOf('=');
      if (j > 0 && /^alias\./i.test(kv.slice(0, j))) inlineAliases.set(kv.slice(6, j).toLowerCase(), kv.slice(j + 1));
      i += 2;
      continue;
    }
    if (a === '-C' && i + 1 < t.length) { dirs.push(t[i + 1]); i += 2; continue; }
    if (eq > 0) { i += 1; continue; }                 // --git-dir=/x : value is attached
    if (GIT_GLOBAL_VALUE_OPTS.has(a) && i + 1 < t.length) { i += 2; continue; }
    i += 1;
  }
  if (i >= t.length) return null;
  return { subcommand: t[i], args: t.slice(i + 1), inlineAliases, dirs };
}

function makeAliasLookup(cwd) {
  return function lookup(name) {
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(name)) return '';  // never pass odd text to git
    try {
      // Argument array, no shell: nothing here is interpolated into a command line.
      return runGit(['config', '--get', 'alias.' + name], {
        cwd: cwd || process.cwd(),
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000,
      }).trim();
    } catch {
      return '';                                          // no such alias / not a repo
    }
  };
}

// The directory a shell command runs in. Kimi Code's Bash tool takes its own `tool_input.cwd`
// (relative paths resolve against the session cwd); the command executes THERE, so a guard reading
// only the payload's session `cwd` would check another repository's branch and staged content.
// Only Kimi defines that field, and Kimi exports KIMI_PLUGIN_ROOT to its hook processes: honouring
// a `cwd` argument on a runtime that ignores it when running the command would let a model point the
// guards at a clean repository. Everything else uses the session cwd, then the hook process cwd.
export function commandCwd(input, env = process.env) {
  const session = typeof input?.cwd === 'string' && input.cwd ? input.cwd : process.cwd();
  const tool = env.KIMI_PLUGIN_ROOT ? input?.tool_input?.cwd : undefined;
  return typeof tool === 'string' && tool ? resolvePath(session, tool) : session;
}

// `git -C a -C b` is CUMULATIVE: each non-absolute -C resolves against the PREVIOUS one, so
// the target is a/b (verified against real git). Taking dirs[0] pointed every git read at a
// strict ancestor of the real target repository, which silently un-scoped the guard.
export function resolveTargetCwd(baseCwd, dirs) {
  return (dirs || []).reduce((acc, d) => resolvePath(acc, d), baseCwd || process.cwd());
}

/**
 * Resolve what a command line will actually make git do.
 *
 * Returns:
 *   subcommands - lowercase Set of every git subcommand reached, after alias expansion
 *   texts       - the original statements PLUS every alias expansion, as command strings. The
 *                 caller needs these because a secret can live inside the ALIAS DEFINITION
 *                 (`alias.ci = "commit -a -m '<token>'"`), where the typed command carries no -m
 *                 at all yet the commit still records that message.
 *   dirs        - values of `git -C <dir>`, so the caller can run its own git reads against the
 *                 repository the command targets rather than the hook process's cwd.
 *
 * `opts.lookup` is injectable so the resolution logic is testable without a live repo;
 * `opts.cwd` selects the repository whose alias table is consulted.
 */
// Shells whose `-c <payload>` runs an inline command line, plus `eval`. Mirrors the list in
// destructive-command-guard.mjs; a payload is re-analyzed as its own statement.
const PAYLOAD_SHELLS = ['bash', 'sh', 'zsh', 'dash', 'ksh', 'powershell', 'pwsh'];

// The inline command line a statement hands to another shell, or null.
//
// Only the COMMAND position counts. Scanning every token meant a statement that merely
// MENTIONS a shell - `echo bash -c "git push origin main"`, `which bash -c git push` - had
// its remaining arguments re-analyzed as a command line and denied. `unwrap` is what resolves
// that position, walking off prefixes and wrappers exactly as it does for a git call.
function innerShellPayload(tokens) {
  const t = unwrap(tokens);
  if (!t.length) return null;
  const name = basename(t[0]).toLowerCase().replace(/\.exe$/, '');
  if (name === 'eval') {
    const text = t.slice(1).join(' ').trim();
    return text || null;
  }
  if (!PAYLOAD_SHELLS.includes(name)) return null;
  for (let j = 1; j < t.length; j += 1) {
    if (/^(?:-command|\/c|-[a-z]*c)$/i.test(t[j])) {
      const text = t.slice(j + 1).join(' ').trim();
      return text || null;
    }
  }
  return null;
}

export function resolveGitCommands(command, opts = {}) {
  const injected = typeof opts === 'function' ? opts : opts.lookup;
  const baseCwd = (typeof opts === 'object' && opts.cwd) || process.cwd();
  // The alias table lives in the repo the command TARGETS, and `-C <dir>` is only discovered while
  // parsing that same call — so the lookup cwd is chosen per call, not once up front. Fixing it in
  // advance made `git -C ../other ci` consult the wrong repository, find no alias, and skip the guard.
  const lookupFor = (call) => injected
    || makeAliasLookup(resolveTargetCwd(baseCwd, call.dirs));

  // PER-STATEMENT scoping. `-C` belongs to the git call that carries it, not to the command line:
  // collecting every `-C` into one shared array let an unrelated `git -C /tmp status;` earlier on
  // the line redirect the COMMIT's own diff read to /tmp, where it found nothing and allowed.
  function walk(statement) {
    const subcommands = new Set();
    const texts = [];
    const payloadTexts = [];
    const dirs = [];
    // `dirs` stays the ordered result; `dirSeen` is the membership test. It used to be
    // `dirs.includes(d)`, which compares each new directory against every one already
    // collected - quadratic, and this path has no input cap, so a long enough command line
    // pushed the hook past its runtime budget. A killed hook renders no decision at all, so
    // the command then proceeds unguarded. A Set rather than a plain object: `-C constructor`
    // and `-C __proto__` must be data, not properties.
    const dirSeen = new Set();
    const seen = new Set();
    const queue = [{ text: statement, depth: 0, viaPayload: false, payloadDepth: 0 }];
    let budget = 64;                                     // hard bound: alias chains cannot spin
    // SEPARATE from the alias budget above. Sharing one means a payload chain can exhaust the
    // budget an alias expansion needs, and exhaustion in this loop is a silent allow.
    let payloadBudget = 128;
    while (queue.length) {
      const item = queue.shift();
      const { text, depth, viaPayload, payloadDepth } = item;
      // Two budgets, spent by whoever the work belongs to. Charging payload-derived dequeues
      // to the alias budget made the separation nominal: a payload chain starved the alias
      // walk at 61 fillers, and running out of THAT budget is a silent allow.
      if (viaPayload) {
        if (payloadBudget <= 0) continue;
        payloadBudget -= 1;
      } else {
        if (budget <= 0) continue;
        budget -= 1;
      }
      if (depth > 5) continue;                           // git itself bounds alias recursion
      const tokens = tokenize(stripGroupWrappers(text));
      const call = gitCall(tokens);
      if (!call) {
        // Not a git call itself - but it may HAND one to another shell. Re-analyze the inline
        // payload as its own statement, bounded independently of the alias walk.
        const inner = payloadDepth < 3 && payloadBudget > 0 ? innerShellPayload(tokens) : null;
        if (inner) {
          payloadBudget -= 1;
          for (const seg of splitStatements(inner)) {
            queue.push({ text: seg, depth, viaPayload: true, payloadDepth: payloadDepth + 1 });
          }
        }
        continue;
      }
      if (viaPayload) {
        // Message text only, collected separately. A payload-derived call contributes no `-C`
        // directory and never reaches the `-F`/`--file` reader, so reaching into a payload does
        // not widen what the commit scanner opens on disk - otherwise
        // `bash -c "git commit -F /etc/passwd"` would newly cause an arbitrary file read. The
        // payload's SUBCOMMANDS still register below, which is what lets branch-guard see a
        // commit or a push through an inner shell.
        payloadTexts.push(text);
      } else {
        texts.push(text);
        for (const d of call.dirs) if (!dirSeen.has(d)) { dirSeen.add(d); dirs.push(d); }
      }
      const sub = String(call.subcommand || '').toLowerCase();
      if (!sub || sub.startsWith('-')) continue;
      subcommands.add(sub);
      const key = depth + ':' + sub;
      if (seen.has(key)) continue;
      seen.add(key);
      // An alias that hides a real git command is ignored by git, so a builtin name is never
      // expanded. This mirrors git's own behaviour and keeps `git status` off the subprocess path.
      if (GIT_BUILTINS.has(sub)) continue;
      // Resolution order mirrors git: inline `-c alias.x=y` wins over stored config.
      const inline = call.inlineAliases.get(sub);
      const expansion = inline !== undefined ? inline : lookupFor(call)(sub);
      if (!expansion) continue;
      if (expansion.startsWith('!')) {
        // `!`-alias: the expansion is a shell command line, so re-analyze it as one.
        for (const seg of splitStatements(expansion.slice(1))) {
          queue.push({ text: seg, depth: depth + 1, viaPayload, payloadDepth });
        }
      } else {
        queue.push({ text: 'git ' + expansion, depth: depth + 1, viaPayload, payloadDepth });
      }
    }
    return { subcommands, texts, payloadTexts, dirs };
  }

  const calls = splitStatements(command)
    .map(walk)
    .filter((c) => c.texts.length || c.payloadTexts.length);
  const subcommands = new Set();
  const texts = [];
  const payloadTexts = [];
  const dirs = [];
  const dirSeen = new Set();                             // same reason as in walk() above
  for (const c of calls) {
    for (const s of c.subcommands) subcommands.add(s);
    texts.push(...c.texts);
    payloadTexts.push(...c.payloadTexts);
    for (const d of c.dirs) if (!dirSeen.has(d)) { dirSeen.add(d); dirs.push(d); }
  }
  return { subcommands, texts, payloadTexts, dirs, calls };
}

/**
 * The working directory to run git reads in for a PARTICULAR subcommand — the `-C` chain of the
 * statement that actually invokes it, never a `-C` borrowed from an unrelated statement.
 */
export function targetCwdFor(info, subcommands, baseCwd) {
  return targetCwdsFor(info, subcommands, baseCwd)[0];
}

/**
 * EVERY working directory that a matching subcommand will run in, deduped and in command order.
 *
 * A command line can carry more than one commit — `git -C repoA commit -m ok && git -C repoB
 * commit -m ok2` — and picking only the first match left repoB's staged content completely
 * unscanned while the guard reported clean. A guard has to inspect every repository the command
 * touches, not the first one it happens to name.
 */
export function targetCwdsFor(info, subcommands, baseCwd) {
  const wanted = Array.isArray(subcommands) ? subcommands : [subcommands];
  const matched = (info.calls || []).filter((c) => wanted.some((s) => c.subcommands.has(s)));
  const cwds = matched.map((c) => resolveTargetCwd(baseCwd, c.dirs));
  const seen = new Set();
  const out = [];
  for (const c of cwds) if (!seen.has(c)) { seen.add(c); out.push(c); }
  return out.length ? out : [resolveTargetCwd(baseCwd, [])];
}

/** Subcommands only. Kept as the simple entry point for callers that need nothing else. */
export function resolveGitSubcommands(command, lookup) {
  return resolveGitCommands(command, lookup ? { lookup } : {}).subcommands;
}

/**
 * True when this git command sweeps unstaged TRACKED changes into the commit (`-a` / `--all`).
 *
 * Token-aware on purpose: the previous regex test ran over the raw statement, so an ordinary
 * `git commit -m "docs: describe -a flag behavior"` matched the `-a` inside its own MESSAGE and
 * pulled the whole working tree into the scan — a false block driven by prose.
 */
export function commitSweepsUnstaged(text) {
  const SHORT_M = /^-([A-Za-z]*?)m(.*)$/;
  for (const seg of splitStatements(text)) {
    const t = tokenize(stripGroupWrappers(seg));
    for (let i = 0; i < t.length; i += 1) {
      const a = t[i];
      if (!a.startsWith('-')) continue;
      if (a === '--all') return true;
      if (a === '--message' || a.startsWith('--')) {
        if (a === '--message') i += 1;                 // its value is the next token, not a flag
        continue;
      }
      const m = SHORT_M.exec(a);
      if (m) {                                          // -m / -am: the rest (or next token) is text
        if (!m[2]) i += 1;
        if (m[1].includes('a')) return true;            // -am is BOTH -a and -m
        continue;
      }
      if (/^-[A-Za-z]*a/.test(a)) return true;          // -a, -av, -qa ...
    }
  }
  return false;
}

/**
 * Commit message text carried on the command line (`-m`, `-m<msg>`, `--message`, `--message=`).
 * The message is part of the commit and git persists it forever, so a secret pasted into it must
 * be scanned exactly like a diff line. Returns the message strings, never the surrounding quotes.
 */
export function commitMessages(command) {
  const out = [];
  // Short options bundle: `git commit -am"<msg>"` and `-qam <msg>` are ordinary git, and `-m`
  // consumes the REST of its cluster as the value. Matching only a literal `-m` prefix lost
  // `-am<msg>` entirely (the token starts with `-a`), so a secret pasted there was committed to
  // permanent history unscanned. `--`-prefixed long options are excluded by the character class.
  const SHORT_M = /^-([A-Za-z]*?)m(.*)$/;
  for (const seg of splitStatements(command)) {
    const t = tokenize(seg);
    for (let i = 0; i < t.length; i += 1) {
      const a = t[i];
      if (a === '--message') { if (i + 1 < t.length) { out.push(t[i + 1]); i += 1; } continue; }
      if (a.startsWith('--message=')) { out.push(a.slice('--message='.length)); continue; }
      if (a.startsWith('--')) continue;
      const m = SHORT_M.exec(a);
      if (!m) continue;
      if (m[2]) { out.push(m[2]); continue; }             // attached value: -m<msg> / -am<msg>
      if (i + 1 < t.length) { out.push(t[i + 1]); i += 1; } // separate value: -m <msg> / -am <msg>
    }
  }
  return out;
}

/** Paths given to `-F` / `--file`, whose contents become the commit message. */
export function commitMessageFiles(command) {
  const out = [];
  for (const seg of splitStatements(command)) {
    const t = tokenize(seg);
    for (let i = 0; i < t.length; i += 1) {
      const a = t[i];
      if (a === '-F' || a === '--file') { if (i + 1 < t.length) { out.push(t[i + 1]); i += 1; } continue; }
      if (a.startsWith('--file=')) out.push(a.slice('--file='.length));
    }
  }
  return out;
}

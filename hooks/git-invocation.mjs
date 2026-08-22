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

import { execFileSync } from 'node:child_process';
import { resolve as resolvePath } from 'node:path';
import { expandAnsiCQuotes } from './shell-quoting.mjs';

// Wrappers whose real command follows them (mirrors destructive-command-guard.mjs).
// positional = positional args the wrapper itself consumes before the real command.
const WRAPPERS = {
  sudo: { positional: 0, argOpts: ['-u', '-g', '-p'] },
  env: { positional: 0, argOpts: [] },
  command: { positional: 0, argOpts: [] },
  builtin: { positional: 0, argOpts: [] },
  nohup: { positional: 0, argOpts: [] },
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
export function splitStatements(text) {
  const segs = [];
  let cur = '';
  let q = null;
  const s = String(text ?? '');
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    const n = s[i + 1];
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; continue; }
    if (c === ';' || c === '\n') { segs.push(cur); cur = ''; continue; }
    if ((c === '&' || c === '|') && n === c) { segs.push(cur); cur = ''; i += 1; continue; }
    if (c === '|' || c === '&') { segs.push(cur); cur = ''; continue; }
    cur += c;
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
  let t = tokens.slice();
  for (let guard = 0; guard < 10 && t.length; guard += 1) {
    while (t.length && /^[A-Za-z_]\w*=/.test(t[0])) t = t.slice(1);   // FOO=bar git commit
    if (!t.length) return t;
    const name = basename(t[0]).toLowerCase().replace(/\.exe$/, '');
    const w = WRAPPERS[name];
    if (!w) return t;
    t = t.slice(1);
    for (let i = 0; i < w.positional && t.length; i += 1) {
      if (t[0].startsWith('-')) break;
      t = t.slice(1);
    }
    while (t.length && t[0].startsWith('-')) {
      const opt = t[0];
      t = t.slice(1);
      if (w.argOpts.includes(opt) && t.length) t = t.slice(1);
    }
  }
  return t;
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
      return execFileSync('git', ['config', '--get', 'alias.' + name], {
        cwd: cwd || process.cwd(),
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000,
      }).trim();
    } catch {
      return '';                                          // no such alias / not a repo
    }
  };
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
    const dirs = [];
    const seen = new Set();
    const queue = [{ text: statement, depth: 0 }];
    let budget = 64;                                     // hard bound: alias chains cannot spin
    while (queue.length && budget > 0) {
      budget -= 1;
      const { text, depth } = queue.shift();
      if (depth > 5) continue;                           // git itself bounds alias recursion
      const call = gitCall(tokenize(stripGroupWrappers(text)));
      if (!call) continue;
      texts.push(text);
      for (const d of call.dirs) if (!dirs.includes(d)) dirs.push(d);
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
        for (const seg of splitStatements(expansion.slice(1))) queue.push({ text: seg, depth: depth + 1 });
      } else {
        queue.push({ text: 'git ' + expansion, depth: depth + 1 });
      }
    }
    return { subcommands, texts, dirs };
  }

  const calls = splitStatements(command).map(walk).filter((c) => c.texts.length);
  const subcommands = new Set();
  const texts = [];
  const dirs = [];
  for (const c of calls) {
    for (const s of c.subcommands) subcommands.add(s);
    texts.push(...c.texts);
    for (const d of c.dirs) if (!dirs.includes(d)) dirs.push(d);
  }
  return { subcommands, texts, dirs, calls };
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

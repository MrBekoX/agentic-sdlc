// Child-process hygiene for hooks that run inside a user's (possibly hostile) project.
//
// programOnAbsolutePath(): resolve a program ONLY through absolute PATH entries. Spawning a bare name
// lets Windows search the current directory first - the user's project, where a planted git.exe or
// python3.exe would run - and a relative PATH entry (`.`) does the same on every OS.
//
// runGit(): execFileSync for git with that resolution plus settings a repository cannot use to blind
// or hijack a scanner: no colour (a coloured `+` line is not an added line; `color.diff` outranks
// `color.ui`, so both are pinned), whole-repository diffs (`diff.relative` would hide every file
// outside the session's subdirectory), no fsmonitor program, no repository hooks (an index refresh
// runs `post-index-change`), and for diffs `--text --no-ext-diff --no-textconv` (a `-diff` attribute
// would print "Binary files differ"; an external diff or textconv driver would replace the bytes
// being scanned). Not closable by a setting: a repository `filter.<name>.clean` driver still runs
// when git compares worktree files (hooks/README.md lists it as a residual).
import { execFileSync } from 'node:child_process';
import { accessSync, constants as fsConstants, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const WIN = process.platform === 'win32';
const ABSOLUTE = WIN ? /^(?:[A-Za-z]:[\\/]|\\\\|\/\/)/ : /^\//;

function executableFile(path) {
  try {
    if (!statSync(path).isFile()) return false;
    if (!WIN) accessSync(path, fsConstants.X_OK);
    return true;
  } catch {
    return false; // missing or not executable
  }
}

// Windows accepts a quoted entry (`"C:\Program Files\Git\cmd"`) and strips the quotes when it
// searches PATH; on POSIX a quote is part of the directory name.
export function pathEntries(value, windows = WIN) {
  const entries = String(value ?? '').split(windows ? ';' : ':');
  return windows ? entries.map((entry) => entry.replace(/^"(.*)"$/, '$1')) : entries;
}

export function programOnAbsolutePath(name, env = process.env) {
  const value = String(name ?? '');
  if (ABSOLUTE.test(value)) return executableFile(value) ? value : null;
  if (!value || /[\\/]/.test(value)) return null; // a relative path with a directory part
  // Windows: executables only. Node cannot start a .cmd/.bat without a shell, so those never qualify.
  const names = !WIN ? [value] : /\.(?:exe|com)$/i.test(value) ? [value] : [`${value}.exe`, `${value}.com`];
  for (const entry of pathEntries(env.PATH ?? env.Path)) {
    if (!ABSOLUTE.test(entry)) continue;
    for (const candidate of names) {
      const full = join(entry, candidate);
      if (executableFile(full)) return full;
    }
  }
  return null;
}

// Hooks are disabled by pointing git at a folder inside this plugin that is never created. An empty
// `core.hooksPath=` would send the lookup to `/<hook>` instead: on Windows the current drive's root,
// which other local users can often write.
const NO_HOOKS_DIR = join(dirname(fileURLToPath(import.meta.url)), 'no-repository-hooks');
const GIT_SETTINGS = ['-c', 'color.ui=never', '-c', 'color.diff=never', '-c', 'diff.relative=false',
  '-c', 'core.fsmonitor=false', '-c', `core.hooksPath=${NO_HOOKS_DIR}`];
const DIFF_HARDENING = ['--text', '--no-ext-diff', '--no-textconv'];

// Same contract as execFileSync('git', args, options): returns stdout, throws on failure. A missing
// git also throws, so every caller's existing fail-open catch still applies.
export function runGit(args, options = {}) {
  const git = programOnAbsolutePath('git');
  if (!git) throw new Error('git not found on an absolute PATH entry');
  const argv = args[0] === 'diff' ? ['diff', ...DIFF_HARDENING, ...args.slice(1)] : args;
  const env = { ...(options.env || process.env), NoDefaultCurrentDirectoryInExePath: '1' };
  return execFileSync(git, [...GIT_SETTINGS, ...argv], { ...options, env });
}

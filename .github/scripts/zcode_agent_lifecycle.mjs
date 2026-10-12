// Native install/update/uninstall of a package through the agent CLI bundled with the ZCode desktop
// app, run in Electron's Node mode. ZCode documents no headless installer, so
// scripts/check_native_lifecycle.py has no ZCode recipe; this is the manual-evidence procedure the
// compatibility matrix cites, kept beside the macOS workflow that runs it.
//
// No GUI, no login, no model turn: only `--version` and `plugins ...` subcommands. Every home, data
// and provider path points into a temporary folder; the caller's real ZCode settings and plugin
// records are compared before and after, and the temporary folder is removed.
//
// Usage: node zcode_agent_lifecycle.mjs --exe <ZCode executable> --resources <app resources dir>
//                                       --package <extracted package dir> --receipt <out.json>
//   Windows: --exe <client>/ZCode.exe --resources <client>/resources
//   macOS:   --exe ZCode.app/Contents/MacOS/ZCode --resources ZCode.app/Contents/Resources
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { isAbsolute, join, relative, resolve } from 'node:path';

function option(name) {
  const at = process.argv.indexOf(name);
  if (at < 0 || !process.argv[at + 1]) throw new Error(`missing ${name}`);
  return resolve(process.argv[at + 1]);
}
const EXE = option('--exe');
const RESOURCES = option('--resources');
const PKG = option('--package');
const RECEIPT = option('--receipt');
const ENTRY = join(RESOURCES, 'glm', 'zcode.cjs');

const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
// Compare real paths: macOS reports /private/var/... for the /var/... temporary folder.
const real = (p) => { try { return realpathSync(p); } catch { return resolve(p); } };
const inside = (child, parent) => {
  const r = relative(real(parent), real(child));
  return !!r && !r.startsWith('..') && !isAbsolute(r);
};
function assert(cond, message) { if (!cond) throw new Error(message); }

const realHome = homedir();
const PERSONAL = {
  cli_config_and_plugin_registrations: join(realHome, '.zcode', 'cli', 'config.json'),
  desktop_settings: join(realHome, '.zcode', 'v2', 'setting.json'),
  installed_plugins_record: join(realHome, '.zcode', 'cli', 'plugins', 'installed_plugins.json'),
  marketplaces_record: join(realHome, '.zcode', 'cli', 'plugins', 'known_marketplaces.json'),
};
const snapshot = () => Object.fromEntries(Object.entries(PERSONAL).map(([k, p]) => [k, existsSync(p) ? sha(readFileSync(p)) : null]));

const record = {
  runtime: 'ZCode desktop bundle agent CLI (Electron Node mode)', platform: process.platform,
  desktop_gui_executed: false, account_login: false, model_turns: 0, operations: [], status: 'pending',
  personal_state_check_scope: 'settings/registration content; live logs/cache/session DB excluded',
};
const before = snapshot();
const base = real(mkdtempSync(join(tmpdir(), 'zcode-lifecycle-')));
const scrub = (text) => [base, resolve(base), base.replace(/\\/g, '\\\\')]
  .reduce((out, form) => out.split(form).join('<temporary-root>'), String(text ?? ''));

try {
  const home = join(base, 'home');
  const project = join(base, 'project');
  const catalog = join(base, 'catalog');
  for (const dir of [home, project, join(base, 'appdata'), join(base, 'localappdata'), join(base, 'user-data'), join(base, 'session-data'), join(base, 'provider')]) mkdirSync(dir, { recursive: true });
  const drop = ['ZCODE', 'ZAI_', 'GLM_', 'CODEX_', 'OPENAI_', 'CLAUDE_', 'ANTHROPIC_', 'OTEL_', 'GIT_'];
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !drop.some((p) => k.toUpperCase().startsWith(p))));
  const provider = join(base, 'provider', 'zcode-builtin.json');
  writeFileSync(provider, readFileSync(join(RESOURCES, 'config', 'provider', 'zcode-builtin.json')));
  Object.assign(env, {
    HOME: home, USERPROFILE: home, APPDATA: join(base, 'appdata'), LOCALAPPDATA: join(base, 'localappdata'),
    XDG_CONFIG_HOME: join(home, '.config'), XDG_DATA_HOME: join(home, '.local', 'share'), XDG_CACHE_HOME: join(home, '.cache'),
    ZCODE_DESKTOP_HOME_DIR: home, ZCODE_DESKTOP_USER_DATA_DIR: join(base, 'user-data'),
    ZCODE_DESKTOP_SESSION_DATA_DIR: join(base, 'session-data'), ZCODE_HOME: join(home, '.zcode'),
    ZCODE_STORAGE_DIR: join(home, '.zcode'), ZCODE_DATA_BASE_DIR: home, ELECTRON_RUN_AS_NODE: '1',
    ZCODE_MODEL_TELEMETRY_ENABLED: '0', ZCODE_BUILTIN_PROVIDER_CONFIG_FILE: provider,
    ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE: provider,
    ZCODE_PERSONAL_PROVIDER_CONFIG_FILE: join(home, '.zcode', 'v2', 'provider_config.json'),
  });

  const probe = spawnSync(EXE, ['-e', "process.stdout.write(JSON.stringify({home:require('node:os').homedir()}))"],
    { cwd: project, env, encoding: 'utf8', timeout: 30000, windowsHide: true });
  assert(probe.status === 0, `electron-node probe failed: ${scrub(probe.stderr).slice(0, 300)}`);
  assert(real(JSON.parse(probe.stdout).home) === real(home), 'node home is not isolated');
  record.native_node_home_isolated = true;

  // Plugins must lead argv; a leading --json is treated as a model entry by the bundle.
  const run = (args, { expected = 0, machine = true } = {}) => {
    const argv = [ENTRY, ...args, ...(machine ? ['--json'] : [])];
    const proc = spawnSync(EXE, argv, { cwd: project, env, encoding: 'utf8', timeout: 60000, windowsHide: true });
    const parsed = machine && proc.status === 0 ? JSON.parse(proc.stdout) : null;
    const kept = Array.isArray(parsed) ? parsed.filter((row) => ['agentic-sdlc', 'unrelated-sentinel'].includes(row.name)) : parsed;
    record.operations.push({ args: args.map(scrub), exit: proc.status,
      stdout_json: kept ? JSON.parse(scrub(JSON.stringify(kept))) : null,
      stdout_text: parsed === null ? scrub(proc.stdout).slice(0, 1000) : null, stderr: scrub(proc.stderr).slice(0, 1000) });
    assert(proc.status === expected, `native ${args.slice(0, 3).join(' ')} exited ${proc.status}`);
    return machine && expected === 0 ? parsed : proc.stdout;
  };

  record.agent_cli_version = String(run(['--version'], { machine: false })).trim();
  const source = join(catalog, 'plugins', 'agentic-sdlc');
  cpSync(PKG, source, { recursive: true });
  const marker = join(source, 'lifecycle-marker.txt');
  writeFileSync(marker, 'initial source\n');
  const other = join(catalog, 'plugins', 'unrelated-sentinel');
  mkdirSync(join(other, '.zcode-plugin'), { recursive: true });
  writeFileSync(join(other, '.zcode-plugin', 'plugin.json'), JSON.stringify({ name: 'unrelated-sentinel', version: '1.0.0', description: 'Temporary lifecycle preservation fixture.' }));
  writeFileSync(join(other, 'unrelated-marker.txt'), 'keep this plugin\n');
  const market = JSON.parse(readFileSync(join(source, 'marketplace.json'), 'utf8'));
  market.name = 'native-lifecycle-fixture';
  market.plugins[0].source = './plugins/agentic-sdlc';
  market.plugins.push({ name: 'unrelated-sentinel', version: '1.0.0', source: './plugins/unrelated-sentinel' });
  writeFileSync(join(catalog, 'marketplace.json'), JSON.stringify(market));
  const settings = join(home, '.zcode', 'v2', 'setting.json');
  mkdirSync(join(home, '.zcode', 'v2'), { recursive: true });
  writeFileSync(settings, '{"autoDownloadAndInstallUpdates":false}');
  const settingsBytes = readFileSync(settings);

  run(['plugins', 'validate', source], { machine: false });
  run(['plugins', 'marketplace', 'add', catalog, '--scope', 'user']);
  run(['plugins', 'install', 'unrelated-sentinel@native-lifecycle-fixture', '--scope', 'user']);
  const installResult = run(['plugins', 'install', 'agentic-sdlc@native-lifecycle-fixture', '--scope', 'user']);
  const installed = (name) => {
    const rows = run(['plugins', 'list']).filter((row) => row.name === name);
    assert(rows.length === 1, `expected one installed ${name}`);
    return rows[0];
  };
  const first = installed('agentic-sdlc');
  assert(inside(first.rootPath, base), 'install path escaped the temporary root');
  assert(readFileSync(join(first.rootPath, 'lifecycle-marker.txt')).equals(readFileSync(marker)), 'installed marker differs');
  for (const name of ['hooks/hooks-zcode.json', 'skills/using-agentic-sdlc/SKILL.md', 'docs/runtime-adapter.md']) {
    assert(readFileSync(join(first.rootPath, name)).equals(readFileSync(join(PKG, name))), `installed ${name} differs from the package`);
  }
  const sentinel = installed('unrelated-sentinel');
  assert(inside(sentinel.rootPath, base), 'sentinel path escaped the temporary root');
  const sentinelBytes = readFileSync(join(sentinel.rootPath, 'unrelated-marker.txt'));
  record.initial_install = { version: first.version, enabled: first.enabled,
    scope: installResult?.installed?.[0]?.scope ?? null, skills: first.skillCount,
    hook_declarations: Array.isArray(first.hookDetails) ? first.hookDetails.length : null };

  writeFileSync(marker, 'refreshed source\n');
  const pluginJson = join(source, '.zcode-plugin', 'plugin.json');
  const item = JSON.parse(readFileSync(pluginJson, 'utf8'));
  item.version = '0.4.4';
  writeFileSync(pluginJson, JSON.stringify(item));
  market.plugins[0].version = '0.4.4';
  writeFileSync(join(catalog, 'marketplace.json'), JSON.stringify(market));
  run(['plugins', 'marketplace', 'update', 'native-lifecycle-fixture']);
  run(['plugins', 'update', 'agentic-sdlc@native-lifecycle-fixture', '--scope', 'user']);
  const refreshed = installed('agentic-sdlc');
  assert(inside(refreshed.rootPath, base), 'refreshed path escaped the temporary root');
  assert(refreshed.version === '0.4.4', `refreshed version is ${refreshed.version}`);
  assert(readFileSync(join(refreshed.rootPath, 'lifecycle-marker.txt')).equals(readFileSync(marker)), 'refreshed bytes not observed');
  record.versioned_update = { version: refreshed.version, refreshed_bytes_observed: true };

  run(['plugins', 'uninstall', 'agentic-sdlc@native-lifecycle-fixture'], { expected: 1 });
  run(['plugins', 'uninstall', 'agentic-sdlc@native-lifecycle-fixture', '--force']);
  assert(!run(['plugins', 'list']).some((row) => row.name === 'agentic-sdlc'), 'agentic-sdlc still listed after uninstall');
  const sentinelAfter = installed('unrelated-sentinel');
  assert(JSON.stringify(sentinelAfter) === JSON.stringify(sentinel), 'unrelated plugin record changed');
  assert(readFileSync(join(sentinel.rootPath, 'unrelated-marker.txt')).equals(sentinelBytes), 'unrelated plugin bytes changed');
  assert(readFileSync(settings).equals(settingsBytes), 'isolated settings changed');
  assert(!existsSync(join(home, '.zcode', 'credentials.json')), 'credentials file appeared');
  record.uninstall = { confirmation_required_without_force: true, registration_removed: true };
  record.unrelated_plugin_and_settings_preserved = true;
  record.status = 'passed';
} catch (error) {
  record.status = 'failed';
  record.limitation = scrub(`${error.name}: ${error.message}`).slice(0, 1200);
} finally {
  const after = snapshot();
  record.personal_state_checks = Object.fromEntries(Object.keys(before).map((k) => [k, before[k] === after[k]]));
  record.personal_state_preserved = Object.values(record.personal_state_checks).every(Boolean);
  if (!record.personal_state_preserved) record.status = 'failed';
  writeFileSync(RECEIPT, JSON.stringify(record, null, 2) + '\n');
  rmSync(base, { recursive: true, force: true });
  console.log(`native_zcode=${record.status === 'passed' ? 'passed' : 'failed'} agent_cli=${record.agent_cli_version ?? 'unknown'}`
    + ` skills=${record.initial_install?.skills ?? 'unknown'} hooks=${record.initial_install?.hook_declarations ?? 'unknown'}`
    + ` personal_state_preserved=${record.personal_state_preserved}${record.limitation ? ` limitation=${record.limitation}` : ''}`);
  process.exitCode = record.status === 'passed' ? 0 : 1;
}

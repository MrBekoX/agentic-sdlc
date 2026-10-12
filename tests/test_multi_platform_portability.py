"""Real relocated hook execution and negative controls; not native lifecycle proof."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
MANIFESTS = {runtime: f'.{runtime}-plugin/plugin.json'
             for runtime in ('claude', 'codex', 'kimi', 'zcode', 'grok')}


def load_checker():
    path = REPO / 'scripts/check_plugin_portability.py'
    spec = importlib.util.spec_from_file_location('portability', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_bytes(root):
    # Only runtime payload, no .git, maintainer settings or historical transcripts.
    result = {}
    for directory in ('hooks', 'scripts', 'skills', 'contracts', 'agents', 'commands',
                      'assets', *('.' + name + '-plugin' for name in MANIFESTS)):
        for path in (root / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


class TestPortablePackage(unittest.TestCase):
    def test_all_five_manifests_exist(self):
        for name, rel in MANIFESTS.items():
            with self.subTest(runtime=name):
                self.assertTrue((REPO / rel).is_file(), rel)

    def test_grok_commands_keep_root_out_of_shell_code(self):
        wire = json.loads((REPO / 'hooks/hooks-grok.json').read_text(encoding='utf-8'))
        for group in wire['hooks']['PreToolUse']:
            for entry in group['hooks']:
                self.assertIn('process.env.GROK_PLUGIN_ROOT', entry['command'])
                self.assertIn('pathToFileURL', entry['command'])
                self.assertNotIn('${GROK_PLUGIN_ROOT}', entry['command'])
                self.assertNotIn('commandWindows', entry)

    def test_runtime_dependency_closure(self):
        self.assertEqual(load_checker().portability_errors(package_bytes(REPO)), [])

    def test_missing_handler_is_detected(self):
        data = package_bytes(REPO)
        del data['hooks/destructive-command-guard.mjs']
        errors = load_checker().portability_errors(data)
        self.assertTrue(any('hooks/destructive-command-guard.mjs' in e for e in errors), errors)

    def test_missing_import_is_detected(self):
        data = package_bytes(REPO)
        del data['hooks/shell-quoting.mjs']
        errors = load_checker().portability_errors(data)
        self.assertTrue(any('hooks/shell-quoting.mjs' in e for e in errors), errors)

    def test_machine_launcher_is_rejected(self):
        data = package_bytes(REPO)
        wire = json.loads(data['hooks/hooks-grok.json'])
        wire['hooks']['PreToolUse'][0]['hooks'][0]['command'] = 'node Z:/developer-checkout/hooks/scan-commit.mjs'
        data['hooks/hooks-grok.json'] = json.dumps(wire).encode()
        errors = load_checker().portability_errors(data)
        self.assertTrue(any('absolute_hook_path:hooks/hooks-grok.json' in e for e in errors), errors)

    def test_missing_helper_is_detected(self):
        data = package_bytes(REPO)
        del data['scripts/validate_artifacts.py']
        errors = load_checker().portability_errors(data)
        self.assertTrue(any('scripts/validate_artifacts.py' in e for e in errors), errors)

    def test_stop_only_closure_requires_validator(self):
        data = package_bytes(REPO)
        for path in MANIFESTS.values():
            data.pop(path, None)
        data[MANIFESTS['claude']] = b'{"hooks":"./hooks/hooks-claude.json"}'
        data['hooks/hooks-claude.json'] = json.dumps({'hooks': {'Stop': [{'hooks': [
            {'command': 'node "${CLAUDE_PLUGIN_ROOT}/hooks/flow-step-guard.mjs"'}]}]}}).encode()
        del data['scripts/validate_artifacts.py']
        errors = load_checker().portability_errors(data)
        self.assertIn('hook_dependency_missing:scripts/validate_artifacts.py', errors)

    def test_malformed_manifest_and_hook_file_are_rejected(self):
        checker = load_checker()
        self.assertIn('portability_json_invalid:.grok-plugin/plugin.json',
                      checker.portability_errors({MANIFESTS['grok']: b'[]'}))
        self.assertIn('portability_json_invalid:hooks/grok.json', checker.portability_errors({
            MANIFESTS['grok']: b'{"hooks":"./hooks/grok.json"}', 'hooks/grok.json': b'[]'}))

    def test_control_char_config_path_is_rejected_without_log_injection(self):
        errors = load_checker().portability_errors({MANIFESTS['grok']:
            json.dumps({'hooks': './hooks/ghost\nspoof.json'}).encode()})
        self.assertEqual(errors, ['unsafe_hook_config_path:.grok-plugin/plugin.json'])

    def test_metadata_command_cannot_hide_nested_missing_handler(self):
        wire = {'command': 'node ./hooks/benign.mjs', 'hooks': {'PreToolUse': [{'hooks': [
            {'type': 'command', 'command': 'node ./hooks/missing.mjs'}]}]}}
        errors = load_checker().portability_errors({MANIFESTS['grok']: b'{"hooks":"./hooks/grok.json"}',
            'hooks/grok.json': json.dumps(wire).encode(), 'hooks/benign.mjs': b'// fixture'})
        self.assertIn('hook_dependency_missing:hooks/missing.mjs', errors)

    def test_hook_config_array_paths_are_resolved(self):
        errors = load_checker().portability_errors({MANIFESTS['claude']:
            b'{"hooks":["./hooks/missing.json"]}'})
        self.assertIn('portability_file_missing:hooks/missing.json', errors)

    def test_hook_missing_command_is_rejected(self):
        errors = load_checker().portability_errors({MANIFESTS['kimi']:
            b'{"hooks":[{"event":"PreToolUse","type":"command","cmd":"node ./hooks/guard.mjs"}]}'})
        self.assertIn('portability_hook_invalid:.kimi-plugin/plugin.json', errors)


@unittest.skipUnless(shutil.which('node'), 'node not available')
class TestRelocatedAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "installed çığ $ ` & # % '"
        for rel, data in package_bytes(REPO).items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.project = self.base / 'unrelated target project'
        self.project.mkdir()

    def shell(self):
        if os.name == 'nt':
            executable = shutil.which('pwsh') or shutil.which('powershell')
            self.assertTrue(executable, 'Grok/Kimi Windows PowerShell missing')
            return [executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command']
        return ['/bin/sh', '-c']

    def execute(self, runtime, handler, command, tool_cwd=None):
        payload = {'cwd': str(self.project), 'hook_event_name': 'PreToolUse'}
        if runtime == 'grok':
            payload.update(toolName='run_terminal_command', toolInput={'command': command})
        else:
            payload.update(tool_name='Bash', tool_input={'command': command})
        if tool_cwd is not None:
            payload['tool_input']['cwd'] = str(tool_cwd)
        env = {k: v for k, v in os.environ.items() if not k.startswith('AGENTIC_')}
        env.update(GROK_PLUGIN_ROOT=str(self.root), KIMI_PLUGIN_ROOT=str(self.root),
                   ZCODE_PLUGIN_ROOT=str(self.root), AGENTIC_BRANCH_GUARD_BLOCK='true')
        if runtime == 'zcode':
            argv = [handler['command'], *(arg.replace('${ZCODE_PLUGIN_ROOT}', str(self.root))
                                          for arg in handler['args'])]
        else:
            argv = [*self.shell(), handler['command']]
        # Kimi's documented plugin hook cwd is the installed root; Grok keeps target cwd.
        cwd = self.root if runtime == 'kimi' else self.project
        proc = subprocess.run(argv, input=json.dumps(payload), cwd=cwd, env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def guards(self, runtime):
        manifest = json.loads((self.root / MANIFESTS[runtime]).read_text(encoding='utf-8'))
        if runtime == 'kimi':
            return manifest['hooks']
        wire = json.loads((self.root / manifest['hooks']).read_text(encoding='utf-8'))
        return [h for group in wire['hooks']['PreToolUse'] for h in group['hooks']]

    def test_relocated_command_denials(self):
        for runtime in ('grok', 'kimi', 'zcode'):
            for handler in self.guards(runtime):
                with self.subTest(runtime=runtime, handler=handler):
                    out = self.execute(runtime, handler, 'git reset --hard HEAD')
                    if 'destructive-command-guard.mjs' in json.dumps(handler):
                        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')

    @unittest.skipUnless(shutil.which('git'), 'git not available')
    def test_project_cwd_drives_branch_guard(self):
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.project)], check=True,
                       capture_output=True)
        for runtime in ('grok', 'kimi', 'zcode'):
            handler = next(h for h in self.guards(runtime) if 'branch-guard.mjs' in json.dumps(h))
            with self.subTest(runtime=runtime):
                out = self.execute(runtime, handler, 'git commit -m test')
                self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
                self.assertIn("'main'", out['hookSpecificOutput']['permissionDecisionReason'])
        subprocess.run(['git', '-C', str(self.project), 'symbolic-ref', 'HEAD', 'refs/heads/feature'],
                       check=True, capture_output=True)
        for runtime in ('grok', 'kimi', 'zcode'):
            handler = next(h for h in self.guards(runtime) if 'branch-guard.mjs' in json.dumps(h))
            with self.subTest(runtime=runtime, branch='feature'):
                self.assertEqual(self.execute(runtime, handler, 'git commit -m test'), {})

    @unittest.skipUnless(shutil.which('git'), 'git not available')
    def test_kimi_tool_cwd_selects_the_repository(self):
        # Kimi's Bash tool takes its own tool_input.cwd; the command runs THERE, not in the session
        # cwd. Guards that read only the session cwd checked the wrong repository's branch and
        # staged content, so a commit on `main` in the tool cwd passed as if it were elsewhere.
        subprocess.run(['git', 'init', '-q', '-b', 'feature', str(self.project)], check=True,
                       capture_output=True)
        other = self.base / 'other repo ğ'
        other.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(other)], check=True, capture_output=True)
        (other / 'config.txt').write_text('TOKEN = ghp_' + 'a1B2' * 9 + '\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(other), 'add', 'config.txt'], check=True, capture_output=True)
        guards = self.guards('kimi')
        for name, reason in (('branch-guard.mjs', "'main'"), ('scan-commit.mjs', None)):
            handler = next(h for h in guards if name in json.dumps(h))
            with self.subTest(handler=name):
                out = self.execute('kimi', handler, 'git commit -m test', tool_cwd=other)
                self.assertEqual(out.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
                if reason:
                    self.assertIn(reason, out['hookSpecificOutput']['permissionDecisionReason'])

    @unittest.skipUnless(shutil.which('git'), 'git not available')
    def test_tool_cwd_is_ignored_outside_kimi(self):
        # Only Kimi's Bash tool runs in tool_input.cwd. On another runtime a model-supplied `cwd`
        # argument must not move the guards off the repository the command actually runs in.
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.project)], check=True,
                       capture_output=True)
        clean = self.base / 'clean feature repo'
        clean.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'feature', str(clean)], check=True, capture_output=True)
        guard = str(self.root / 'hooks' / 'branch-guard.mjs')
        payload = {'cwd': str(self.project), 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                   'tool_input': {'command': 'git commit -m test', 'cwd': str(clean)}}
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('AGENTIC_') and k not in ('KIMI_PLUGIN_ROOT', 'KIMI_CODE_HOME')}
        env['AGENTIC_BRANCH_GUARD_BLOCK'] = 'true'
        node = shutil.which('node')
        self.assertTrue(node, 'node missing')
        proc = subprocess.run([node, guard], input=json.dumps(payload),
                              cwd=self.project, env=env, capture_output=True, text=True,
                              encoding='utf-8', timeout=25)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(out.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
        self.assertIn("'main'", out['hookSpecificOutput']['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()

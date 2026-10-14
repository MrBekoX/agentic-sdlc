"""Check declared runtime hook paths and dependency closure without executing a package.

Accept archive bytes or read the runtime files in a directory. This is static package
evidence, not proof of a runtime's discovery, trust or model behavior.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import re


MANIFESTS = tuple(f'.{runtime}-plugin/plugin.json'
                  for runtime in ('claude', 'codex', 'kimi', 'zcode', 'grok', 'cursor'))
ROOT_REF = re.compile(r'\$\{(?:CLAUDE_PLUGIN_ROOT|PLUGIN_ROOT|KIMI_PLUGIN_ROOT|ZCODE_PLUGIN_ROOT|GROK_PLUGIN_ROOT)\}/([A-Za-z0-9_./-]+)')
ENV_REF = re.compile(r"\.join\(process\.env\.(?:PLUGIN_ROOT|GROK_PLUGIN_ROOT|CURSOR_PLUGIN_ROOT),'hooks','([a-z0-9-]+\.mjs)'\)")
RELATIVE_REF = re.compile(r'\./(hooks/[a-z0-9-]+\.mjs)')
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?:^|[\s'\"])/[^\s'\"]+)")
IMPORT_REF = re.compile(r"(?:from\s*|import\s*(?:\(\s*)?)[\"'](\.{1,2}/[^\"']+\.mjs)[\"']")
# These readers also open non-module resources. Static JS imports cannot reveal them.
EXTRA_DEPENDENCIES = {
    'hooks/flow-evidence.mjs': ('hooks/flow-requirements.json', 'scripts/validate_artifacts.py'),
    'hooks/codex-flow-evidence.mjs': ('hooks/flow-requirements.json', 'scripts/validate_artifacts.py'),
    'hooks/flow-order-guard.mjs': ('hooks/flow-requirements.json', 'scripts/validate_artifacts.py'),
    'hooks/flow-order-guard-codex.mjs': ('scripts/validate_artifacts.py',),
}


def _handlers(value):
    if isinstance(value, dict):
        if ('command' in value or 'commandWindows' in value or 'event' in value
                or value.get('type') in ('command', 'process')):
            yield value
        # Metadata with a command key must not conceal nested real handlers.
        for child in value.values():
            yield from _handlers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _handlers(child)


def _safe_relative(path):
    return (bool(path) and not path.startswith('/') and '\\' not in path
            and not re.match(r'^[A-Za-z]:', path) and '..' not in path.split('/')
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in path))


def portability_errors(members: dict[str, bytes]) -> list[str]:
    """Validate only components declared by present manifests; public skills-only is valid.

    Historical evidence, docs and synthetic test paths are not executable paths.
    Diagnostics contain filenames/error types, never command or credential contents.
    """
    errors, pending = set(), []

    def read_json(name):
        if name not in members:
            errors.add(f'portability_file_missing:{name}')
            return None
        try:
            value = json.loads(members[name])
        except (ValueError, UnicodeDecodeError):
            errors.add(f'portability_json_invalid:{name}')
            return None
        if not isinstance(value, (dict, list)):
            errors.add(f'portability_json_invalid:{name}')
            return None
        return value

    for manifest_path in MANIFESTS:
        if manifest_path not in members:
            continue
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            errors.add(f'portability_json_invalid:{manifest_path}')
            continue
        wire = manifest.get('hooks')
        wires = wire if isinstance(wire, list) else [wire]
        resolved = []
        for entry in wires:
            if entry is None:
                continue
            wire_path = manifest_path
            if isinstance(entry, str):
                wire_path = entry.removeprefix('./')
                if not _safe_relative(wire_path):
                    errors.add(f'unsafe_hook_config_path:{manifest_path}')
                    continue
                entry = read_json(wire_path)
            if entry is not None and not isinstance(entry, dict):
                errors.add(f'portability_json_invalid:{wire_path}')
                continue
            resolved.extend((wire_path, handler) for handler in _handlers(entry))
        for wire_path, handler in resolved:
            if not isinstance(handler.get('command'), str):
                errors.add(f'portability_hook_invalid:{wire_path}')
                continue
            refs = []
            for field in ('command', 'commandWindows', 'args'):
                values = handler.get(field, [])
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    errors.add(f'portability_hook_invalid:{wire_path}')
                    continue
                for text in values:
                    if not isinstance(text, str):
                        errors.add(f'portability_hook_invalid:{wire_path}')
                        continue
                    if ABSOLUTE_PATH.search(text):
                        errors.add(f'absolute_hook_path:{wire_path}')
                    refs += ROOT_REF.findall(text) + RELATIVE_REF.findall(text)
                    refs += ['hooks/' + name for name in ENV_REF.findall(text)]
            if not refs:
                errors.add(f'unresolved_hook_handler:{wire_path}')
            for ref in refs:
                if not _safe_relative(ref):
                    errors.add(f'unsafe_hook_handler_path:{wire_path}')
                else:
                    pending.append(ref)

    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if path not in members or not members[path]:
            errors.add(f'hook_dependency_missing:{path}')
            continue
        if path.endswith('.mjs'):
            text = members[path].decode('utf-8', 'replace')
            for rel in IMPORT_REF.findall(text):
                target = posixpath.normpath(posixpath.join(posixpath.dirname(path), rel))
                if not _safe_relative(target):
                    errors.add(f'unsafe_hook_import:{path}')
                else:
                    pending.append(target)
            pending.extend(EXTRA_DEPENDENCIES.get(path, ()))
    return sorted(errors)


def runtime_members(root: Path) -> dict[str, bytes]:
    result = {}
    for directory in ('hooks', 'scripts', 'skills', 'contracts', 'agents', 'commands', 'assets',
                      *(path.split('/')[0] for path in MANIFESTS)):
        for path in (root / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    members = runtime_members(args.root)
    errors = portability_errors(members)
    errors += [f'portability_manifest_missing:{path}' for path in MANIFESTS if path not in members]
    for error in sorted(errors):
        print('error=' + error)
    print('plugin_portability=' + ('failed' if errors else 'passed'))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())

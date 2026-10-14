"""Validate the Cursor plugin manifest and the components it discovers.

This is a static package check. It does not start Cursor, install the plugin,
or prove that the IDE loaded a skill.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?:^|[\s'\"])/)")


def _read_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    found = {}
    for line in text[4:end].splitlines():
        if not line or line[0] in " \t" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        found[key.strip()] = value.strip().strip("'\"")
    return found


def _relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        return False
    if re.match(r"^[A-Za-z]:", value) or ".." in value.replace("\\", "/").split("/"):
        return False
    return not any(ord(char) < 32 for char in value)


def _component_dirs(manifest: dict, root: Path, field: str, default: str) -> list[Path]:
    declared = manifest.get(field, default)
    values = declared if isinstance(declared, list) else [declared]
    paths = []
    for value in values:
        if not isinstance(value, str):
            continue
        relative = value.removeprefix("./")
        paths.append(root / relative)
    return paths


def validate(root: Path) -> list[str]:
    """Return stable error codes. An empty list means the package is structurally valid."""
    errors = []
    manifest_path = root / ".cursor-plugin" / "plugin.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return ["cursor_manifest_invalid:.cursor-plugin/plugin.json"]
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        errors.append("cursor_name_invalid")
    if not isinstance(manifest.get("description"), str) or not manifest["description"].strip():
        errors.append("cursor_description_missing")
    author = manifest.get("author")
    if not isinstance(author, dict) or not str(author.get("name") or "").strip():
        errors.append("cursor_author_missing")
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        version = ""
    if manifest.get("version") != version:
        errors.append("cursor_version_mismatch")
    for field in ("skills", "agents", "commands", "rules", "hooks", "logo"):
        value = manifest.get(field)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is None:
                continue
            if not isinstance(item, str) or not _relative_path(item):
                errors.append(f"cursor_path_unsafe:{field}")
                continue
            if not (root / item.removeprefix("./")).exists():
                errors.append(f"cursor_path_missing:{field}:{item}")
    if (root / "hooks" / "hooks.json").exists():
        errors.append("cursor_default_hooks_json_present")
    if (root / "plugin.json").exists():
        errors.append("cursor_root_plugin_json_present")

    skills = [path for directory in _component_dirs(manifest, root, "skills", "skills")
              for path in directory.glob("*/SKILL.md")]
    if len(skills) < 16:
        errors.append("cursor_skills_incomplete")
    for skill in skills:
        front = _frontmatter(skill.read_text(encoding="utf-8"))
        if front.get("name") != skill.parent.name or not front.get("description"):
            errors.append(f"cursor_skill_frontmatter:{skill.parent.name}")

    agents = [path for directory in _component_dirs(manifest, root, "agents", "agents")
              for path in directory.glob("*.md")]
    if not agents:
        errors.append("cursor_agents_missing")
    for agent in agents:
        front = _frontmatter(agent.read_text(encoding="utf-8"))
        if front.get("name") != agent.stem or not NAME_RE.fullmatch(front.get("name", "")) or not front.get("description"):
            errors.append(f"cursor_agent_frontmatter:{agent.stem}")

    commands = [path for directory in _component_dirs(manifest, root, "commands", "commands")
                for path in directory.glob("*.md")]
    if not any(path.stem == "git-safety-check" for path in commands):
        errors.append("cursor_command_missing:git-safety-check")
    for command in commands:
        front = _frontmatter(command.read_text(encoding="utf-8"))
        if front.get("name") != command.stem or not front.get("description"):
            errors.append(f"cursor_command_frontmatter:{command.stem}")

    rules = [path for directory in _component_dirs(manifest, root, "rules", "rules")
             for path in directory.glob("*.mdc")]
    if not rules:
        errors.append("cursor_rules_missing")
    for rule in rules:
        front = _frontmatter(rule.read_text(encoding="utf-8"))
        if not front.get("description") or front.get("alwaysApply") not in {"true", "false"}:
            errors.append(f"cursor_rule_frontmatter:{rule.name}")

    hook_field = manifest.get("hooks")
    hook_path = root / str(hook_field).removeprefix("./")
    hooks = _read_json(hook_path)
    if not isinstance(hooks, dict) or not isinstance(hooks.get("hooks"), dict):
        errors.append("cursor_hooks_invalid")
    else:
        text = hook_path.read_text(encoding="utf-8")
        if ABSOLUTE_PATH.search(text) or "${CURSOR_PLUGIN_ROOT}" in text:
            errors.append("cursor_hook_path_interpolated")
        if "process.env.CURSOR_PLUGIN_ROOT" not in text or "cursor-launch.mjs" not in text:
            errors.append("cursor_hook_root_unresolved")
        for event in ("beforeShellExecution", "preToolUse", "sessionStart", "stop"):
            if event not in hooks["hooks"]:
                errors.append(f"cursor_hook_event_missing:{event}")
        for event, entries in hooks["hooks"].items():
            if not isinstance(entries, list) or not entries:
                errors.append(f"cursor_hook_event_empty:{event}")
                continue
            for entry in entries:
                command = entry.get("command") if isinstance(entry, dict) else None
                if not isinstance(command, str) or not command.startswith("node -e "):
                    errors.append(f"cursor_hook_command_invalid:{event}")
    marketplace = _read_json(root / ".cursor-plugin" / "marketplace.json")
    plugins = marketplace.get("plugins") if isinstance(marketplace, dict) else None
    entry = plugins[0] if isinstance(plugins, list) and plugins else None
    if not isinstance(entry, dict) or entry.get("name") != "agentic-sdlc" or entry.get("source") != ".":
        errors.append("cursor_marketplace_invalid")
    elif entry.get("version") != manifest.get("version"):
        errors.append("cursor_marketplace_version_mismatch")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = validate(root)
    for error in errors:
        print("error=" + error)
    skills = len(list((root / "skills").glob("*/SKILL.md"))) if (root / "skills").is_dir() else 0
    print(f"cursor_skills={skills}")
    print("cursor_plugin=" + ("failed" if errors else "passed"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

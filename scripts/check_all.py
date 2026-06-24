"""Self-contained repo quality gate (the `make check` target).

Why this exists: a prod-ready skill lab needs one local command that fails loudly on a broken
skill or a red validator test. It is deliberately
self-contained (stdlib only, no skill-creator dependency) so it runs on a clean machine
without the marketplace plugin present. It mirrors quick_validate's frontmatter rules rather
than importing them, so the check ships with the repo.

Output: sorted flat `key=value` lines + `check_all=passed|failed`. Exit 1 on any error.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
TESTS_DIR = REPO / "tests"
# Valid Claude Code skill frontmatter for a REPO gate. Broader than skill-creator's
# quick_validate (a packaging validator): `user-invocable` / `argument-hint` are legitimate
# here and used by our flow skills. `.skill` packaging still enforces the stricter set.
ALLOWED_KEYS = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
    "user-invocable", "argument-hint", "model", "disable-model-invocation",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def split_frontmatter(text):
    """Return (frontmatter, body) or (None, None) if no leading --- block."""
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    return text[3:end], text[end + 4:]


def check_skill(skill_dir, errors, warnings):
    sk = skill_dir / "SKILL.md"
    name_hint = skill_dir.name
    if not sk.exists():
        errors.append(f"missing_skill_md:{name_hint}")
        return
    text = sk.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    if fm is None:
        errors.append(f"no_frontmatter:{name_hint}")
        return
    # Top-level keys must be in the allowed set.
    for key in re.findall(r"(?m)^([A-Za-z][\w-]*):", fm):
        if key not in ALLOWED_KEYS:
            errors.append(f"bad_frontmatter_key:{name_hint}:{key}")
    # name: present, kebab-case, matches directory.
    m = re.search(r"(?m)^name:\s*(.+)$", fm)
    name = m.group(1).strip() if m else ""
    if not name:
        errors.append(f"no_name:{name_hint}")
    elif name != name_hint:
        errors.append(f"name_dir_mismatch:{name_hint}:{name}")
    elif not NAME_RE.match(name):
        errors.append(f"name_not_kebab:{name_hint}")
    # description: present, no angle brackets (the quick_validate rejection class).
    m = re.search(r"(?m)^description:\s*(.+)$", fm)
    desc = m.group(1).strip() if m else ""
    if not desc:
        errors.append(f"no_description:{name_hint}")
    elif "<" in desc or ">" in desc:
        errors.append(f"angle_bracket_in_description:{name_hint}")
    # body length budget (lines after the closing frontmatter ---).
    blines = (body or "").count("\n")
    if blines > 500:
        warnings.append(f"body_over_500:{name_hint}:{blines}")


def main():
    errors, warnings = [], []
    checked = 0
    if not SKILLS_DIR.is_dir():
        print("error=skills_dir_missing")
        print("check_all=failed")
        return 1
    for d in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        check_skill(d, errors, warnings)
        checked += 1

    # Run the deterministic-validator unit tests.
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(TESTS_DIR)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tests_ok = res.returncode == 0
    if not tests_ok:
        errors.append("validator_tests_failed")

    fields = {
        "skills_checked": checked,
        "validator_tests": "pass" if tests_ok else "fail",
        "check_all": "failed" if errors else "passed",
    }
    lines = [f"{k}={v}" for k, v in fields.items()]
    lines += [f"warning={w}" for w in warnings]
    lines += [f"error={e}" for e in errors]
    for line in sorted(lines):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

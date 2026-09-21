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
# Shared Agent Skills fields only. Runtime-specific agent metadata has its own gate;
# an external toolkit validator may implement a narrower, version-specific subset.
ALLOWED_KEYS = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")



# The suites this script runs, named rather than discovered. `validator_tests=` reports these
# and nothing else; the rest of the suite is the documented gate's fourth command. A pattern
# that matches no file is a failing test (tests/test_gate_composition.py), so this list cannot
# quietly shrink to nothing.
VALIDATOR_TEST_PATTERNS = (
    "test_validate_artifacts.py",          # the artifact validator itself
    "test_validator_cli_unchanged.py",     # its CLI characterization
    "test_validator_resolver_parity.py",   # it must agree with resolve_work_package.py
    "test_work_package_resolution.py",     # the resolver that consumes what it validates
)


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
    if len(name) > 64:
        errors.append(f"name_too_long:{name_hint}")
    # description: present, no angle brackets (the quick_validate rejection class).
    m = re.search(r"(?m)^description:\s*(.+)$", fm)
    desc = m.group(1).strip() if m else ""
    if not desc:
        errors.append(f"no_description:{name_hint}")
    elif "<" in desc or ">" in desc:
        errors.append(f"angle_bracket_in_description:{name_hint}")
    if len(desc) > 1024:
        errors.append(f"description_too_long:{name_hint}")
    if re.match(r"^[\"']?Use\b", desc):
        errors.append(f"imperative_description:{name_hint}")
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

    # Run the deterministic-validator unit tests - and ONLY those.
    #
    # This used to be an unrestricted `discover -s tests`, which collects all ~49 suites. The
    # key it reports is `validator_tests=`, AGENTS.md documents this script as "skill
    # frontmatter + validator tests", and the documented gate's fourth command already runs the
    # whole suite - so the unrestricted form both mislabelled its result and made a gate run
    # execute ~1300 tests twice (440 s against 1.3 s here). `.pre-commit-config.yaml` runs this
    # script, so every commit silently paid that full run, and a guard that blocks routine safe
    # work for minutes is one that gets switched off.
    #
    # Coverage is unchanged: everything dropped here is collected by
    # `python3 -m unittest discover -s tests`, and tests/test_gate_composition.py fails if any
    # suite stops being covered by a documented gate command.
    tests_ok = True
    for pattern in VALIDATOR_TEST_PATTERNS:
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(TESTS_DIR), "-p", pattern],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if res.returncode != 0:
            tests_ok = False
            # Surface the captured unittest output so CI/logs can name the failing test.
            dumped = (res.stderr or "").strip() or (res.stdout or "").strip()
            if dumped:
                sys.stderr.write(dumped + "\n")
    if not tests_ok:
        errors.append("validator_tests_failed")

    fields = {
        # Named so a contributor reading only this output is not misled about coverage: this
        # script is the FAST subset, and the rest of the suite is the gate's fourth command.
        "suites_not_run_here": "python3 -m unittest discover -s tests",
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

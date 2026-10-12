"""Docs test for the per-environment Codex hook trust steps (spec AC132, decision D24).

The pure helpers return named violations, so the synthetic cases prove each rule fires without
editing a real file. The real-file tests read README.md, .codex-plugin/README.md,
docs/troubleshooting.md, docs/runtime-adapter.md and the ledger row state in the current release's
docs/release-evidence-<VERSION>.md.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ("Windows", "macOS", "Linux", "WSL")
CHECK_SCRIPT = "check_codex_hook_trust.py"
TRUSTED_LINE = "codex_hook_trust=trusted"
BYPASS_FLAG = "--dangerously-bypass-hook-trust"
SECTION_HEADING = "Codex hook trust"
SECTION_ANCHOR = "troubleshooting.md#codex-hook-trust"
LEDGER_ROW = "hook_trust_list_records"
VERIFIED_CLAIM = re.compile(r"\bverified through\b", re.IGNORECASE)


def section(text, heading):
    """Return the lines under `## <heading>` up to the next `## ` heading, or None when absent."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## " + heading:
            body = []
            for rest in lines[index + 1 :]:
                if rest.startswith("## "):
                    break
                body.append(rest)
            return body
    return None


def ledger_row_state(ledger, row_id):
    """Return the State cell of a `## Required release rows` row, or None when the row is absent."""
    for line in ledger.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) > 3 and cells[1] == "`" + row_id + "`":
            return cells[3]
    return None


def trust_section_violations(text, ledger_state=None):
    """A row may claim `verified through` only while the ledger row it cites reads PASS (spec AC132)."""
    body = section(text, SECTION_HEADING)
    if body is None:
        return ["missing_section"]
    violations = []
    rows = [line for line in body if line.startswith("|")]
    for env in ENVIRONMENTS:
        matches = [row for row in rows if re.match(r"^\|\s*" + re.escape(env) + r"\s*\|", row)]
        if len(matches) != 1:
            violations.append("environment_row_count:" + env)
            continue
        row = matches[0]
        if "/hooks" not in row:
            violations.append("row_missing_hooks_step:" + env)
        if CHECK_SCRIPT not in row:
            violations.append("row_missing_check_command:" + env)
        if "node" not in row.lower():
            violations.append("row_missing_node_requirement:" + env)
        if VERIFIED_CLAIM.search(row) and ledger_state != "PASS":
            violations.append("unverified_platform_claim:" + env)
    joined = "\n".join(body)
    if "not live-tested" not in joined:
        violations.append("missing_not_live_tested")
    if TRUSTED_LINE not in joined:
        violations.append("missing_trusted_line")
    for line in body:
        if BYPASS_FLAG in line:
            violations.append("bypass_flag_presented")
            break
    return violations


def install_doc_violations(rel, text):
    violations = []
    if CHECK_SCRIPT not in text:
        violations.append("missing_check_script:" + rel)
    if TRUSTED_LINE not in text:
        violations.append("missing_trusted_line:" + rel)
    if SECTION_ANCHOR not in text:
        violations.append("missing_section_link:" + rel)
    return violations


def runtime_adapter_violations(text):
    violations = []
    if "trustStatus" not in text:
        violations.append("missing_trust_status")
    if "does not prove that a hook runs" not in text:
        violations.append("missing_trust_limit")
    return violations


def _row(env, hooks="/hooks", check="python3 scripts/check_codex_hook_trust.py", node="`node` on PATH"):
    return f"| {env} | `~/.codex/config.toml` | {hooks} | {node} | {check} | not live-tested |"


GOOD_SECTION = "\n".join(
    [
        "## Codex hook trust",
        "",
        "| Environment | Codex config location | Trust step | node | Check command | Verification state |",
        "|---|---|---|---|---|---|",
        *[_row(env) for env in ENVIRONMENTS],
        "",
        "A trusted plugin prints `codex_hook_trust=trusted`.",
        "",
        "## Next",
    ]
)


class TestTrustSectionRules(unittest.TestCase):
    def test_trust_section_rule_synthetic_cases(self):
        self.assertEqual(trust_section_violations(GOOD_SECTION), [])
        cases = [
            ("missing_section", GOOD_SECTION.replace("## Codex hook trust", "## Hooks")),
            ("environment_row_count:macOS", GOOD_SECTION.replace(_row("macOS") + "\n", "")),
            ("environment_row_count:WSL", GOOD_SECTION.replace(_row("WSL"), _row("WSL") + "\n" + _row("WSL"))),
            ("row_missing_hooks_step:Linux", GOOD_SECTION.replace(_row("Linux"), _row("Linux", hooks="open the UI"))),
            ("row_missing_check_command:Windows", GOOD_SECTION.replace(_row("Windows"), _row("Windows", check="run the check"))),
            ("row_missing_node_requirement:Linux", GOOD_SECTION.replace(_row("Linux"), _row("Linux", node="runtime on PATH"))),
            ("missing_not_live_tested", GOOD_SECTION.replace("not live-tested", "see ledger")),
            ("missing_trusted_line", GOOD_SECTION.replace("codex_hook_trust=trusted", "trusted")),
            ("bypass_flag_presented", GOOD_SECTION.replace("## Next", "Or run codex " + BYPASS_FLAG + ".\n\n## Next")),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, trust_section_violations(text))
        claimed = GOOD_SECTION.replace(_row("Linux"), _row("Linux").replace("| not live-tested |", "| verified through WSL Ubuntu 24.04 |"))
        for state in (None, "not-run", "FAIL"):
            with self.subTest(name="unverified_platform_claim:Linux", state=state):
                self.assertIn("unverified_platform_claim:Linux", trust_section_violations(claimed, state))
        self.assertEqual(trust_section_violations(claimed, "PASS"), [])

    def test_ledger_row_state_reads_the_state_cell(self):
        ledger = "| Row id | BR3 required | State |\n|---|---|---|\n| `hook_trust_list_records` | yes | not-run |"
        self.assertEqual(ledger_row_state(ledger, LEDGER_ROW), "not-run")
        self.assertIsNone(ledger_row_state(ledger, "other_row"))

    def test_install_doc_and_adapter_rule_synthetic_cases(self):
        good = "Run `python3 scripts/check_codex_hook_trust.py`; expect `codex_hook_trust=trusted` (docs/troubleshooting.md#codex-hook-trust)."
        self.assertEqual(install_doc_violations("x.md", good), [])
        self.assertIn("missing_check_script:x.md", install_doc_violations("x.md", good.replace(CHECK_SCRIPT, "check.py")))
        self.assertIn("missing_trusted_line:x.md", install_doc_violations("x.md", good.replace(TRUSTED_LINE, "trusted")))
        self.assertIn("missing_section_link:x.md", install_doc_violations("x.md", good.replace(SECTION_ANCHOR, "troubleshooting.md")))
        adapter = "`trustStatus` is read. The check does not prove that a hook runs."
        self.assertEqual(runtime_adapter_violations(adapter), [])
        self.assertIn("missing_trust_status", runtime_adapter_violations(adapter.replace("trustStatus", "status")))
        self.assertIn("missing_trust_limit", runtime_adapter_violations(adapter.replace("does not prove that a hook runs", "proves it")))


class TestRealTrustDocs(unittest.TestCase):
    def test_troubleshooting_trust_section_covers_every_environment(self):
        text = (REPO / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        ledger = (REPO / "docs" / f"release-evidence-{version}.md").read_text(encoding="utf-8")
        state = ledger_row_state(ledger, LEDGER_ROW)
        self.assertIsNotNone(state)
        self.assertEqual(trust_section_violations(text, state), [])

    def test_install_docs_give_the_check_command_and_trusted_line(self):
        violations = []
        for rel in ("README.md", ".codex-plugin/README.md"):
            violations += install_doc_violations(rel, (REPO / rel).read_text(encoding="utf-8"))
        self.assertEqual(violations, [])

    def test_runtime_adapter_states_the_trust_check_limit(self):
        text = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        self.assertEqual(runtime_adapter_violations(text), [])


if __name__ == "__main__":
    unittest.main()

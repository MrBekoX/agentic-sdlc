"""The strategy step of the sdlc runner (plan Task 6): scripts/sdlc_runner/strategy.py.

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §9 (mechanisms, runtime rows,
mechanism-bearing keys, mandated fresh keys, `strategy confirm`); design §5.7 (default map rule
table, strategy_ok, read-only re-entry, escalate amends only missing keys).

The default-map and validation cases are pure functions over the real flows/_shared.json. The
confirm, card and escalate cases run the in-process CLI on the harness of
tests/test_sdlc_engine.py (temp plugin root, temp git project, no paid CLI).
"""
import json
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import EngineCase, card_fields  # noqa: E402
from sdlc_runner import manifest, schema, strategy  # noqa: E402

SHARED = manifest.load_shared(REPO)
PLAIN = {"explore_mode": "single", "deps": "stdlib_only", "toolchain": "absent"}
EVERYTHING = {"explore_mode": "parallel", "deps": "external", "toolchain": "present"}
ALL_KEYS = {"context", "draft", "draft.critic", "implement", "security", "quality-gates", "quality-review",
            "audit", "docs-check"}


def _flow(flow_id):
    return manifest.load_flow(REPO, flow_id)


def _state(runtime="codex", probes=None, options=(), form="gated", work_type="feature"):
    return {"runtime": runtime, "probes": dict(probes or PLAIN), "options": list(options), "form": form,
            "work_type": work_type}


def _map(flow_id, runtime, capabilities, probes=None, options=(), overrides=(), work_type="feature"):
    """A strategy.json body: the default map, the declared capabilities and the overrides."""
    base = strategy.default_map(_flow(flow_id), SHARED, dict(probes or PLAIN), runtime, list(options),
                                work_type=work_type)
    entries = {key: dict(entry) for key, entry in base["entries"].items()}
    for key, mechanism, reason in overrides:
        entries[key] = {"mechanism": mechanism, "reason": reason, "source": "override"}
    return strategy.build_map(runtime, capabilities, entries)


def _caps(workflow="no", subagent="yes", team="no"):
    return {"workflow": workflow, "subagent": subagent, "team": team}


class TestDefaultMap(unittest.TestCase):
    def test_default_map_never_defaults_to_an_engine(self):
        for runtime in ("claude", "grok"):
            with self.subTest(runtime=runtime):
                entries = strategy.default_map(_flow("feature"), SHARED, PLAIN, runtime, ["loop"])["entries"]
                self.assertEqual(entries["draft"]["mechanism"], "runner-loop")
                self.assertEqual(entries["draft.critic"]["mechanism"], "runner-loop")
                for key in ("security", "audit"):
                    self.assertEqual(entries[key]["mechanism"], "subagent", key)
                self.assertEqual(entries["implement"]["mechanism"], "main")
                self.assertTrue(all(entry["source"] == "default" and entry["reason"] for entry in entries.values()))
                self.assertNotIn("workflow", {entry["mechanism"] for entry in entries.values()})

    def test_default_map_codex_uses_runner_loop(self):
        entries = strategy.default_map(_flow("feature"), SHARED, PLAIN, "codex", ["loop"])["entries"]
        self.assertEqual((entries["draft"]["mechanism"], entries["draft.critic"]["mechanism"]),
                         ("runner-loop", "runner-loop"))
        self.assertEqual(entries["security"]["mechanism"], "subagent")
        # A runtime with no sub-agents runs the loop inline and degrades the fresh-context gates.
        entries = strategy.default_map(_flow("feature"), SHARED, PLAIN, "other", ["loop"])["entries"]
        self.assertEqual(entries["draft"]["mechanism"], "runner-loop-inline")
        self.assertEqual((entries["security"]["mechanism"], entries["audit"]["mechanism"]),
                         ("inline-degraded", "inline-degraded"))
        # ZCode's explicit-request workflow is never a default.
        entries = strategy.default_map(_flow("feature"), SHARED, PLAIN, "zcode", ["loop"])["entries"]
        self.assertEqual(entries["draft"]["mechanism"], "runner-loop")

    def test_default_map_covers_only_applicable_keys(self):
        keys = set(strategy.default_map(_flow("feature"), SHARED, PLAIN, "codex", [])["entries"])
        self.assertEqual(keys, {"context", "draft", "draft.critic", "implement", "security", "audit"})
        keys = set(strategy.default_map(_flow("full"), SHARED, PLAIN, "codex", [])["entries"])
        self.assertEqual(keys, {"context", "draft", "draft.critic", "implement", "security", "audit"})
        keys = set(strategy.default_map(_flow("full"), SHARED, EVERYTHING, "codex", ["quality-review"])["entries"])
        self.assertEqual(keys, ALL_KEYS)
        self.assertEqual(set(strategy.default_map(_flow("test"), SHARED, PLAIN, "codex", [])["entries"]),
                         {"context", "implement"})
        parallel = strategy.default_map(_flow("feature"), SHARED, EVERYTHING, "codex", [])["entries"]
        self.assertEqual(parallel["context"]["mechanism"], "subagent")  # one analyst per layer


def _imported(files):
    state = _state()
    state["imported"] = list(files)
    return state


class TestImportedFact(unittest.TestCase):
    """The strategy decides `applies_when.imported` the way the engine does (plan Task 2)."""

    FLOW = {"steps": [
        {"id": "security", "mechanism_key": "security", "applies_when": {"imported": True}},
        {"id": "audit", "mechanism_key": "audit", "applies_when": {"imported": False}},
        {"id": "context", "mechanism_key": "context"},
    ]}

    def test_strategy_facts_carry_imported(self):
        self.assertEqual(strategy._state_facts(_imported(["spec/x.md"]))["imported"], ["spec/x.md"])
        self.assertEqual(strategy._state_facts(_state())["imported"], [])
        self.assertEqual(strategy._facts({}, [], imported=["spec/x.md"])["imported"], ["spec/x.md"])
        self.assertEqual(strategy.applicable_keys(self.FLOW, strategy._state_facts(_state())),
                         ["context", "audit"])
        self.assertEqual(strategy.applicable_keys(self.FLOW, strategy._state_facts(
            _imported(["spec/x.md"]))), ["context", "security"])
        from sdlc_runner import engine

        for imported in ([], ["spec/x.md"]):
            state = _imported(imported)
            for step in self.FLOW["steps"]:
                with self.subTest(imported=imported, step=step["id"]):
                    engine_says = engine.applies(types.SimpleNamespace(state=state), step)[0]
                    self.assertEqual(strategy._applies(step, strategy._state_facts(state)), engine_says)

    def test_default_map_takes_imported(self):
        flow = {"id": "x", "steps": self.FLOW["steps"]}
        plain = strategy.default_map(flow, SHARED, PLAIN, "codex", [])["entries"]
        given = strategy.default_map(flow, SHARED, PLAIN, "codex", [], imported=["spec/x.md"])["entries"]
        self.assertEqual(set(plain), {"context", "audit"})
        self.assertEqual(set(given), {"context", "security"})


class TestValidate(unittest.TestCase):
    def test_override_needs_reason(self):
        errors = strategy.validate(_map("feature", "codex", _caps(), overrides=[("implement", "subagent", " ")]),
                                   _flow("feature"), _state())
        self.assertTrue(any(e.startswith("/entries/implement") and "reason" in e for e in errors), errors)
        self.assertEqual(strategy.validate(_map("feature", "codex", _caps(),
                                                overrides=[("implement", "subagent", "big plan")]),
                                           _flow("feature"), _state()), [])

    def test_mechanism_must_be_within_declared_capabilities(self):
        loop = ["loop"]
        errors = strategy.validate(_map("feature", "codex", _caps(subagent="no"), options=loop), _flow("feature"),
                                   _state(options=loop))
        self.assertTrue(any(e.startswith("/entries/draft:") and "subagent=yes" in e for e in errors), errors)
        self.assertTrue(any(e.startswith("/entries/security:") for e in errors), errors)
        errors = strategy.validate(_map("feature", "claude", _caps(workflow="no"), options=loop,
                                        overrides=[("draft", "workflow", "the user asked for the engine")]),
                                   _flow("feature"), _state(runtime="claude", options=loop))
        self.assertTrue(any(e.startswith("/entries/draft:") and "workflow=yes" in e for e in errors), errors)
        errors = strategy.validate(_map("feature", "codex", _caps(workflow="yes"), options=loop,
                                        overrides=[("draft", "workflow", "try it")]), _flow("feature"),
                                   _state(options=loop))
        self.assertTrue(any(e.startswith("/entries/draft:") and "no workflow engine" in e for e in errors), errors)
        errors = strategy.validate(_map("feature", "codex", _caps(), options=loop), _flow("feature"),
                                   _state(runtime="claude", options=loop))
        self.assertTrue(any(e.startswith("/runtime") for e in errors), errors)
        missing = _map("feature", "codex", _caps(), options=loop)
        del missing["entries"]["audit"]
        errors = strategy.validate(missing, _flow("feature"), _state(options=loop))
        self.assertTrue(any(e.startswith("/entries/audit") and "missing" in e for e in errors), errors)

    def test_engine_override_needs_a_reason_on_every_runtime(self):
        loop = ["loop"]
        message = "an engine runs only on the user's explicit request (an override with a reason)"
        for runtime in ("claude", "grok", "zcode"):
            with self.subTest(runtime=runtime):
                state = _state(runtime=runtime, options=loop)
                caps = _caps(workflow="yes")
                for key in ("draft", "draft.critic"):
                    forced = _map("feature", runtime, caps, options=loop)
                    forced["entries"][key] = {"mechanism": "workflow", "reason": "the runtime has an engine",
                                              "source": "default"}
                    errors = strategy.validate(forced, _flow("feature"), state)
                    self.assertTrue(any(e.startswith("/entries/%s:" % key) and message in e for e in errors), errors)
                    asked = _map("feature", runtime, caps, options=loop,
                                 overrides=[(key, "workflow", "the user said: use the workflow engine")])
                    self.assertEqual(strategy.validate(asked, _flow("feature"), state), [])

    def test_mandated_keys_never_main(self):
        for key in ("draft.critic", "security", "audit", "quality-review"):
            with self.subTest(key=key):
                strategy_map = _map("full", "codex", _caps(), probes=EVERYTHING, options=["quality-review"],
                                    overrides=[(key, "main", "faster")])
                errors = strategy.validate(strategy_map, _flow("full"),
                                           _state(probes=EVERYTHING, options=["quality-review"]))
                self.assertTrue(any(e.startswith("/entries/%s:" % key) and "never main" in e for e in errors), errors)

    def test_inline_degraded_needs_no_or_denied_capability(self):
        override = [("security", "inline-degraded", "no sub-agent tool in this session")]
        errors = strategy.validate(_map("feature", "codex", _caps(), overrides=override), _flow("feature"), _state())
        self.assertTrue(any(e.startswith("/entries/security:") and "subagent=no or denied" in e for e in errors), errors)
        for declared in ("no", "denied"):
            with self.subTest(subagent=declared):
                overrides = override + [("draft", "runner-loop-inline", "no sub-agents"),
                                        ("draft.critic", "runner-loop-inline", "no sub-agents"),
                                        ("audit", "inline-degraded", "no sub-agents")]
                strategy_map = _map("feature", "codex", _caps(subagent=declared), overrides=overrides)
                self.assertEqual(strategy.validate(strategy_map, _flow("feature"), _state()), [])
                self.assertEqual({d["key"] for d in strategy_map["degraded"]},
                                 {"security", "draft", "draft.critic", "audit"})


class TestConfirm(EngineCase):
    def test_confirm_writes_strategy_json_and_logs(self):
        self.start()
        code, text = self.sdlc("strategy", "confirm", "--capabilities", "workflow=no,subagent=no,team=no")
        self.assertEqual(code, 4, text)
        self.assertIn("error=strategy_refused:/entries/draft:", text)
        self.assertFalse((self.pkg() / "strategy.json").exists())
        code, text = self.sdlc("strategy", "confirm", "--capabilities", "workflow=no,subagent=no,team=no",
                               "--set", "draft=runner-loop-inline:no sub-agent tool in this session",
                               "--set", "security=inline-degraded:no sub-agent tool in this session")
        self.assertEqual(code, 0, text)
        data = json.loads((self.pkg() / "strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(schema.validate(data, manifest.load_schema("strategy")), [])
        self.assertEqual(data["capabilities"], {"workflow": "no", "subagent": "no", "team": "no"})
        self.assertEqual(data["entries"]["security"],
                         {"mechanism": "inline-degraded", "reason": "no sub-agent tool in this session",
                          "source": "override"})
        self.assertEqual(data["entries"]["context"]["source"], "default")
        self.assertEqual({d["key"] for d in data["degraded"]}, {"draft", "security"})
        record = self.records("strategy")[0]
        self.assertEqual(record["capabilities"], data["capabilities"])
        self.assertEqual([o["key"] for o in record["overrides"]], ["draft", "security"])
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "context")
        code, text = self.sdlc("strategy", "confirm", "--capabilities", "workflow=no,subagent=yes,team=no")
        self.assertEqual(code, 4, text)
        self.assertIn("error=strategy_already_confirmed", text)
        code, text = self.sdlc("strategy", "confirm", "--capabilities", "workflow=maybe")
        self.assertEqual(code, 2, text)

    def test_strategy_step_never_goes_stale(self):
        self.start()
        self.confirm_strategy()
        self.next()
        self.write("src/app.py", b"def add(a, b):\n    return a - b\n")
        self.put("strategy.json", (self.pkg() / "strategy.json").read_text(encoding="utf-8").replace(
            '"main"', '"subagent"', 1))
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "context")
        st = self.state()
        self.assertEqual((st["steps"]["strategy"]["state"], st["steps"]["strategy"]["visits"]), ("done", 1))
        self.assertEqual(self.records("stale", step="strategy"), [])

    def test_card_prints_resolved_mechanism_and_degraded(self):
        self.start()
        code, text = self.card()
        self.assertIn("confirm=", text)  # the strategy card names the confirm command and the default map
        self.assertIn("security:subagent", card_fields(text)["default"])
        code, text = self.sdlc("strategy", "confirm", "--capabilities", "workflow=no,subagent=no,team=no",
                               "--set", "draft=runner-loop-inline:no sub-agent tool",
                               "--set", "security=inline-degraded:no sub-agent tool")
        self.assertEqual(code, 0, text)
        code, text = self.next()
        self.assertEqual((card_fields(text)["mechanism"], card_fields(text)["degraded"]), ("main", "none"))
        code, text = self.advance_to("security")
        self.assertEqual((card_fields(text)["mechanism"], card_fields(text)["degraded"]),
                         ("inline-degraded", "subagent:no"))

    def test_escalate_amends_draft_keys_within_declared_capabilities(self):
        self.start("--option", "loop", flow="test", work_type="test", runtime="claude", work_id="tst")
        self.confirm_strategy("tst", "workflow=denied,subagent=yes,team=no")
        self.next("tst")
        code, text = self.sdlc("escalate", "feature", "--slug", "tst", "--reason", "production code must change")
        self.assertEqual(code, 0, text)
        after = json.loads((self.pkg("tst") / "strategy.json").read_text(encoding="utf-8"))
        self.assertEqual((after["entries"]["draft"]["mechanism"], after["entries"]["draft.critic"]["mechanism"]),
                         ("runner-loop", "runner-loop"))
        self.assertEqual(after["entries"]["security"]["mechanism"], "subagent")
        self.assertEqual(strategy.validate(after, manifest.load_flow(self.root, "feature"), self.state("tst")), [])

    def test_escalate_amends_only_missing_keys(self):
        self.start("--option", "quality-review", flow="feature", work_id="feat")
        self.confirm_strategy(slug="feat")
        self.next("feat")
        before = json.loads((self.pkg("feat") / "strategy.json").read_text(encoding="utf-8"))
        code, text = self.sdlc("escalate", "full", "--slug", "feat", "--reason", "it needs the full flow")
        self.assertEqual(code, 0, text)
        after = json.loads((self.pkg("feat") / "strategy.json").read_text(encoding="utf-8"))
        for key, entry in before["entries"].items():
            self.assertEqual(after["entries"][key], entry, key)
        self.assertEqual(after["capabilities"], before["capabilities"])
        added = set(after["entries"]) - set(before["entries"])
        self.assertEqual(added, {"quality-review"})
        self.assertEqual(after["entries"]["quality-review"]["mechanism"], "subagent")
        self.assertIn("escalate", after["entries"]["quality-review"]["reason"])
        self.assertEqual(self.records("escalate", slug="feat")[0]["strategy_added"], ["quality-review"])
        self.assertEqual(strategy.validate(after, manifest.load_flow(self.root, "full"), self.state("feat")), [])


if __name__ == "__main__":
    unittest.main()

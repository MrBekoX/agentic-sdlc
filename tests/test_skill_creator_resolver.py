import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "skill-authoring" / "scripts" / "resolve_skill_creator.py"


def load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_skill_creator", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FULL_TOOLKIT_FILES = (
    "scripts/quick_validate.py",
    "scripts/aggregate_benchmark.py",
    "eval-viewer/generate_review.py",
    "eval-viewer/viewer.html",
    "scripts/run_eval.py",
    "scripts/run_loop.py",
    "scripts/improve_description.py",
    "scripts/generate_report.py",
    "scripts/utils.py",
    "scripts/package_skill.py",
    "references/schemas.md",
)


def make_skill_creator_root(path, files=FULL_TOOLKIT_FILES):
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: skill-creator\n---\n", encoding="utf-8")
    (path / "scripts").mkdir()
    for relative in files:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n", encoding="utf-8")


class TestSkillCreatorResolver(unittest.TestCase):
    def test_default_skips_minimal_codex_for_complete_claude_toolkit(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            codex = Path(tmp) / "codex-system"
            claude = Path(tmp) / "claude-official"
            make_skill_creator_root(codex, ["scripts/quick_validate.py"])
            make_skill_creator_root(claude)
            with mock.patch.object(resolver, "candidate_paths", return_value=[
                ("codex-system", codex), ("claude-official-cache:test", claude),
            ]):
                self.assertEqual(resolver.discover(), ("claude-official-cache:test", claude.resolve()))

    def test_validate_only_accepts_minimal_toolkit(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "minimal"
            make_skill_creator_root(root, ["scripts/quick_validate.py"])
            with mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", root)]):
                self.assertEqual(resolver.discover(("validate",)), ("codex-system", root.resolve()))

    def test_missing_capabilities_report_resources_and_do_not_install(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "minimal"
            make_skill_creator_root(root, ["scripts/quick_validate.py"])
            buf = io.StringIO()
            with (
                mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", root)]),
                mock.patch.object(resolver, "install_with_claude") as install,
                contextlib.redirect_stdout(buf),
            ):
                rc = resolver.main([])
            install.assert_not_called()
        self.assertEqual(rc, 2)
        self.assertIn("skill_creator_status=missing_capabilities", buf.getvalue())
        for resource in ("scripts/package_skill.py", "eval-viewer/viewer.html", "references/schemas.md"):
            self.assertIn(resource, buf.getvalue())

    def test_viewer_requires_its_template_and_packager_requires_validator(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "partial"
            make_skill_creator_root(root, ["eval-viewer/generate_review.py", "scripts/package_skill.py"])
            with mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", root)]):
                self.assertIsNone(resolver.discover(("viewer",)))
                self.assertIsNone(resolver.discover(("package",)))

    def test_required_resources_must_be_files(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "partial"
            make_skill_creator_root(root, [])
            (root / "scripts/quick_validate.py").mkdir()
            with mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", root)]):
                self.assertIsNone(resolver.discover(("validate",)))

    def test_cli_can_request_multiple_capabilities(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "review"
            make_skill_creator_root(root, [
                "scripts/aggregate_benchmark.py", "eval-viewer/generate_review.py", "eval-viewer/viewer.html",
            ])
            buf = io.StringIO()
            with (
                mock.patch.object(resolver, "candidate_paths", return_value=[("skill_creator_root", root)]),
                contextlib.redirect_stdout(buf),
            ):
                rc = resolver.main(["--require", "benchmark", "viewer"])
        self.assertEqual(rc, 0)
        self.assertIn("skill_creator_required=benchmark,viewer", buf.getvalue())
        self.assertIn("skill_creator_trust=explicit-unverified", buf.getvalue())

    def test_install_rechecks_capabilities_not_just_identity(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "minimal"
            make_skill_creator_root(root, ["scripts/quick_validate.py"])
            buf = io.StringIO()
            with (
                mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", root)]),
                mock.patch.object(resolver, "install_with_claude", return_value=(0, "installed")) as install,
                contextlib.redirect_stdout(buf),
            ):
                rc = resolver.main(["--install"])
            install.assert_called_once_with()
        self.assertEqual(rc, 3)
        self.assertIn("skill_creator_status=missing_after_install", buf.getvalue())
        self.assertIn("scripts/package_skill.py", buf.getvalue())

    def test_discovers_explicit_env_root(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-creator"
            make_skill_creator_root(root)
            expected = root.resolve()
            with mock.patch.dict("os.environ", {"SKILL_CREATOR_ROOT": str(root)}, clear=True):
                found = resolver.discover()
        self.assertIsNotNone(found)
        source, path = found
        self.assertEqual(source, "skill_creator_root")
        self.assertEqual(path, expected)

    def test_discovery_returns_canonical_candidate_path(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-creator"
            make_skill_creator_root(root)
            # Keep the input noncanonical, independently of Windows 8.3 aliases.
            candidate = root / ".." / root.name
            with mock.patch.object(resolver, "candidate_paths", return_value=[("codex-system", candidate)]):
                self.assertEqual(resolver.discover(), ("codex-system", root.resolve()))

    def test_rejects_shape_compatible_wrong_skill(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-creator"
            make_skill_creator_root(root)
            (root / "SKILL.md").write_text("---\nname: impostor\n---\n", encoding="utf-8")
            with (
                mock.patch.object(resolver, "home", return_value=Path(tmp) / "home"),
                mock.patch.dict("os.environ", {"SKILL_CREATOR_ROOT": str(root)}, clear=True),
            ):
                self.assertIsNone(resolver.discover())

    def test_wrong_explicit_identity_preserves_official_cache_fallback(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wrong-skill"
            make_skill_creator_root(root)
            (root / "SKILL.md").write_text("---\nname: impostor\n---\n", encoding="utf-8")
            fixture_home = Path(tmp) / "home"
            official = fixture_home / ".claude/plugins/cache/claude-plugins-official/skill-creator/fixture/skills/skill-creator"
            make_skill_creator_root(official)
            with (
                mock.patch.object(resolver, "home", return_value=fixture_home),
                mock.patch.dict("os.environ", {"SKILL_CREATOR_ROOT": str(root)}, clear=True),
            ):
                self.assertEqual(resolver.discover(), ("claude-official-cache:fixture", official.resolve()))

    def test_does_not_recursively_scan_arbitrary_cache(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            make_skill_creator_root(home / ".claude/plugins/cache/untrusted/pkg/skill-creator")
            with (
                mock.patch.object(resolver, "home", return_value=home),
                mock.patch.object(resolver, "codex_home", return_value=Path(tmp) / "codex"),
                mock.patch.dict("os.environ", {}, clear=True),
            ):
                self.assertIsNone(resolver.discover())

    def test_missing_reports_install_command_without_installing(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex = Path(tmp) / "codex"
            buf = io.StringIO()
            with (
                mock.patch.object(resolver, "home", return_value=home),
                mock.patch.object(resolver, "codex_home", return_value=codex),
                mock.patch.dict("os.environ", {}, clear=True),
                contextlib.redirect_stdout(buf),
            ):
                rc = resolver.main([])
        self.assertEqual(rc, 2)
        out = buf.getvalue()
        self.assertIn("skill_creator_status=missing", out)
        self.assertIn("claude plugin install skill-creator@claude-plugins-official", out)

    def test_install_fallback_runs_then_resolves_again(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex = Path(tmp) / "codex"

            def fake_install():
                make_skill_creator_root(codex / "skills" / ".system" / "skill-creator")
                return 0, "installed"

            buf = io.StringIO()
            with (
                mock.patch.object(resolver, "home", return_value=home),
                mock.patch.object(resolver, "codex_home", return_value=codex),
                mock.patch.object(resolver, "install_with_claude", side_effect=fake_install),
                mock.patch.dict("os.environ", {}, clear=True),
                contextlib.redirect_stdout(buf),
            ):
                rc = resolver.main(["--install"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("install_exit=0", out)
        self.assertIn("skill_creator_status=installed", out)
        self.assertIn("skill_creator_source=codex-system", out)


if __name__ == "__main__":
    unittest.main()

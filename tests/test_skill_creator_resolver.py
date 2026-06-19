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


def make_skill_creator_root(path):
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: skill-creator\n---\n", encoding="utf-8")
    (path / "scripts").mkdir()


class TestSkillCreatorResolver(unittest.TestCase):
    def test_discovers_explicit_env_root(self):
        resolver = load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-creator"
            make_skill_creator_root(root)
            with mock.patch.dict("os.environ", {"SKILL_CREATOR_ROOT": str(root)}, clear=True):
                found = resolver.discover()
        self.assertIsNotNone(found)
        source, path = found
        self.assertEqual(source, "skill_creator_root")
        self.assertEqual(path, root)

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

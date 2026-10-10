import contextlib
import copy
import importlib.util
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit


REPO = Path(__file__).resolve().parents[1]
LINK_RECORD = REPO / "docs" / "publication" / "link-checks.json"
LINK_ENTRY_KEYS = {"url", "checked_at", "http_status", "auth"}
MAINTAINER_DECISION_KEYS = {"decided_on", "maintainer_reference"}
# \Z, not $: `$` also matches before a trailing newline.
CHECKED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
DECIDED_ON_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")


def load_link_record(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def link_record_file_violations(raw):
    # Task 2 file contract over the raw bytes: LF only, trailing newline, entries sorted by url.
    violations = []
    if b"\r" in raw:
        violations.append("record_not_lf")
    if not raw.endswith(b"\n"):
        violations.append("record_no_trailing_newline")
    record = json.loads(raw.decode("utf-8"))
    urls = [entry.get("url") for entry in record if isinstance(entry, dict)] if isinstance(record, list) else []
    if not all(isinstance(url, str) for url in urls) or urls != sorted(urls):
        violations.append("record_not_sorted_by_url")
    return violations


def record_entry(record, url):
    # Exact string match: a trailing slash is a different, unchecked URL.
    for entry in record:
        if isinstance(entry, dict) and entry.get("url") == url:
            return entry
    return None


def top_level_urls(manifest):
    urls = {field: manifest[field] for field in ("homepage", "repository") if field in manifest}
    author = manifest.get("author")
    if isinstance(author, dict) and "url" in author:
        urls["author.url"] = author["url"]
    return urls


def maintainer_decision_violations(decision):
    if not isinstance(decision, dict) or set(decision) != MAINTAINER_DECISION_KEYS:
        return ["maintainer_decision_keys"]
    violations = []
    if not isinstance(decision["decided_on"], str) or not DECIDED_ON_RE.match(decision["decided_on"]):
        violations.append("maintainer_decision_date")
    reference = decision["maintainer_reference"]
    if not isinstance(reference, str) or not reference.startswith("https://"):
        violations.append("maintainer_reference_not_https")
    return violations


def link_record_violations(record, manifest):
    if not isinstance(record, list):
        return ["record_not_array"]
    violations = []
    seen = set()
    for entry in record:
        if not isinstance(entry, dict):
            violations.append("entry_not_object")
            continue
        if set(entry) - {"maintainer_decision"} != LINK_ENTRY_KEYS:
            violations.append("entry_keys")
        if entry.get("auth") != "none":
            violations.append("auth_not_none")
        status = entry.get("http_status")
        if type(status) is not int or not 100 <= status <= 599:
            violations.append("http_status_invalid")
        checked_at = entry.get("checked_at")
        if not isinstance(checked_at, str) or not CHECKED_AT_RE.match(checked_at):
            violations.append("checked_at_invalid")
        url = entry.get("url")
        if url in seen:
            violations.append("duplicate_url")
        seen.add(url)
        if "maintainer_decision" in entry:
            violations.extend(maintainer_decision_violations(entry["maintainer_decision"]))
    for url in top_level_urls(manifest).values():
        if record_entry(record, url) is None:
            violations.append("top_level_url_unrecorded")
    return violations


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}\Z")


def relative_luminance(hex_color):
    # WCAG 2.x sRGB relative luminance.
    linear = []
    for start in (1, 3, 5):
        channel = int(hex_color[start:start + 2], 16) / 255
        linear.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(a, b):
    lighter, darker = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def asset_violations(interface, package_root):
    # PNG IHDR geometry via struct only; no imaging dependency in the repository gate.
    root = Path(package_root).resolve()
    violations = []
    for key in ("logo", "composerIcon"):
        rel = interface.get(key)
        if not isinstance(rel, str) or not rel:
            violations.append("asset_missing")
            continue
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            violations.append("asset_outside_package")
            continue
        if not path.is_file():
            violations.append("asset_missing")
            continue
        data = path.read_bytes()
        if data[:8] != PNG_SIGNATURE:
            violations.append("asset_not_png")
            continue
        if len(data) < 24:
            violations.append("asset_geometry")
            continue
        width, height = struct.unpack(">II", data[16:24])
        if width != height or not 48 <= width <= 4096:
            violations.append("asset_geometry")
    return violations


PRODUCT_PREFIX = "https://github.com/MrBekoX/agentic-sdlc"


def _string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


def _interface_url_violations(interface, record):
    violations = []
    for key, url in interface.items():
        if not key.endswith("URL"):
            continue
        if url == "":
            if key in ("privacyPolicyURL", "websiteURL"):
                violations.append("empty_url")
            continue
        parts = urlsplit(url) if isinstance(url, str) else None
        if parts is None or parts.scheme != "https":
            violations.append("non_https")
            continue
        if parts.path.endswith("/LICENSE"):
            violations.append("license_as_policy")
        entry = record_entry(record, url)
        if entry is None or type(entry.get("http_status")) is not int or entry["http_status"] != 200 or entry.get("auth") != "none":
            violations.append("unchecked_link")
        product_owned = url == PRODUCT_PREFIX or url.startswith(PRODUCT_PREFIX + "/")
        if not product_owned and (entry is None or maintainer_decision_violations(entry.get("maintainer_decision"))):
            violations.append("not_product_owned")
    return violations


def listing_violations(manifest, record, package_root):
    interface = manifest.get("interface", {})
    violations = []
    brand = interface.get("brandColor")
    if not isinstance(brand, str) or not HEX_COLOR_RE.match(brand):
        violations.append("brand_color_format")
    elif contrast_ratio(brand, "#FFFFFF") < 2.0:
        violations.append("brand_color_contrast")
    if "brandColorDark" in interface:
        dark = interface["brandColorDark"]
        if not isinstance(dark, str) or not HEX_COLOR_RE.match(dark):
            violations.append("brand_color_dark_format")
        elif contrast_ratio(dark, "#212121") < 2.0:
            violations.append("brand_color_dark_contrast")
    # Lengths are Python code points; the listing text is ASCII today.
    if len(interface.get("displayName", "")) > 30:
        violations.append("display_name_too_long")
    if len(interface.get("shortDescription", "")) > 30:
        violations.append("short_description_too_long")
    if len(interface.get("longDescription", "")) > 4000:
        violations.append("long_description_too_long")
    if interface.get("category") != "Developer Tools":
        violations.append("category_not_developer_tools")
    prompts = interface.get("defaultPrompt", [])
    if len(prompts) > 3:
        violations.append("too_many_default_prompts")
    if any(len(prompt) > 128 for prompt in prompts):
        violations.append("default_prompt_too_long")
    if "termsOfServiceURL" in interface:
        violations.append("terms_of_service_present")
    for value in _string_values(manifest):
        parts = urlsplit(value)
        if parts.hostname == "docs.github.com" and "/site-policy/" in parts.path:
            violations.append("third_party_policy_page")
            break
    violations.extend(_interface_url_violations(interface, record))
    for url in top_level_urls(manifest).values():
        if record_entry(record, url) is None:
            violations.append("top_level_url_unrecorded")
    if "screenshots" in interface:
        violations.append("screenshots_present")
    violations.extend(asset_violations(interface, package_root))
    return violations


def personal_path_violations(rel, text, install_doc):
    # Codex resolves the personal catalog source `./plugins/agentic-sdlc` under the home directory.
    violations = []
    if "./plugins/agentic-sdlc" in text and "~/.codex/plugins/agentic-sdlc" in text:
        violations.append(f"wrong_personal_mapping:{rel}")
    if install_doc:
        if "~/plugins/agentic-sdlc" not in text:
            violations.append(f"install_doc_missing_home_path:{rel}")
        if "~/.codex/plugins/agentic-sdlc" in text:
            violations.append(f"install_doc_names_wrong_path:{rel}")
    return violations


def codex_manifest_format_violations(manifest):
    violations = []
    if manifest.get("skills") != "./skills/":
        violations.append("skills_not_declared")
    if manifest.get("hooks") != "./hooks/hooks-codex.json":
        violations.append("hooks_not_legacy_codex")
    return violations


def _require_git_checkout(testcase):
    # Copied from test_release_readiness_docs so each module loads on its own.
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0 or Path(proc.stdout.strip()).resolve() != REPO.resolve():
        testcase.skipTest("not a git checkout of this tree: ignore rules need git")


class TestPackagingMetadata(unittest.TestCase):
    def test_shipping_format_keeps_codex_hooks_loadable(self):
        # Codex 0.154.0 loader.rs suppresses all AgentPlugin hooks. The native
        # comparison observes 0 portable hooks versus 8 legacy hooks. Revisit
        # this release contract only after a newer native probe proves parity.
        self.assertFalse((REPO / "plugin.json").exists())
        plugin = json.loads((REPO / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["hooks"], "./hooks/hooks-codex.json")
        self.assertEqual(codex_manifest_format_violations(plugin), [])
        docs = (REPO / ".codex-plugin/README.md").read_text(encoding="utf-8")
        self.assertIn("0.154.0", docs)
        self.assertIn("portable", docs)

    def test_committed_tree_has_no_root_portable_manifest(self):
        # The release archive is built only from a committed tree (BR13).
        _require_git_checkout(self)
        proc = subprocess.run(
            ["git", "ls-tree", "--name-only", "HEAD", "--", "plugin.json"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_presentation_assets_exist_inside_package(self):
        interface = json.loads((REPO / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["interface"]
        self.assertRegex(interface["brandColor"], r"^#[0-9A-Fa-f]{6}\Z")
        self.assertEqual(asset_violations(interface, REPO), [])
        for asset in [interface["composerIcon"], interface["logo"]]:
            self.assertTrue(asset.startswith("./assets/"), asset)
            self.assertTrue((REPO / asset).resolve().is_relative_to((REPO / "assets").resolve()), asset)
            size = (REPO / asset).stat().st_size
            self.assertGreater(size, 100)
            self.assertLessEqual(size, 5 * 1024 * 1024)

    def test_plugin_manifests_exist_and_match_version(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "agentic-sdlc")
        self.assertEqual(plugin["version"], version)
        self.assertEqual(plugin["hooks"], "./hooks/hooks-claude.json")
        self.assertEqual(marketplace["plugins"][0]["name"], "agentic-sdlc")
        self.assertEqual(marketplace["plugins"][0]["version"], version)
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertEqual(codex_plugin["name"], "agentic-sdlc")
        self.assertEqual(codex_plugin["version"], version)
        self.assertEqual(codex_plugin["skills"], "./skills/")
        self.assertEqual(codex_plugin["hooks"], "./hooks/hooks-codex.json")

    def test_marketplace_name_is_public_and_matches_readme(self):
        mp = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(mp["name"], "mrbekox")
        self.assertNotIn("dev", mp["name"])
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("agentic-sdlc@mrbekox", readme)
        self.assertNotIn("agentic-sdlc@agentic-sdlc-dev", readme)

    def test_public_docs_match_current_version(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        docs = [
            REPO / "README.md",
            REPO / "docs" / "plugin-readme.md",
            REPO / "docs" / "release-readiness.md",
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            self.assertIn(version, text, f"{path.relative_to(REPO)} missing current version")
            self.assertNotIn("0.2.7", text, f"{path.relative_to(REPO)} still references old release")

    def test_runtime_readmes_use_canonical_work_package_paths(self):
        canonical = "docs/agentic-sdlc/"
        legacy = ("docs/specs/", "docs/plans/")
        for rel in (".claude-plugin/README.md", ".codex-plugin/README.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn(canonical, text)
            for old in legacy:
                self.assertNotIn(old, text, f"{rel} still uses legacy artifact path {old}")

    def test_personal_path_rule_synthetic_cases(self):
        both = "Source `./plugins/agentic-sdlc` resolves to `~/.codex/plugins/agentic-sdlc`."
        self.assertEqual(personal_path_violations("guide.md", both, install_doc=False), ["wrong_personal_mapping:guide.md"])
        home = "Source `./plugins/agentic-sdlc` resolves to `~/plugins/agentic-sdlc`."
        self.assertEqual(personal_path_violations("README.md", home, install_doc=True), [])
        wrong_only = "Put the plugin at `~/.codex/plugins/agentic-sdlc`."
        self.assertEqual(
            sorted(personal_path_violations("README.md", wrong_only, install_doc=True)),
            ["install_doc_missing_home_path:README.md", "install_doc_names_wrong_path:README.md"],
        )
        self.assertEqual(personal_path_violations("notes.md", "No Codex catalog path here.", install_doc=False), [])

    def test_reader_docs_map_personal_catalog_to_home_plugins(self):
        # Filesystem glob, not git: the rule also runs inside an extracted archive.
        install_docs = {"README.md", ".codex-plugin/README.md", "docs/troubleshooting.md"}
        candidates = [REPO / "README.md", REPO / ".claude-plugin/README.md", REPO / ".codex-plugin/README.md", REPO / "hooks/README.md"]
        candidates += sorted((REPO / "docs").glob("*.md")) + sorted((REPO / "docs" / "publication").glob("*.md"))
        violations = []
        for path in candidates:
            if not path.is_file():
                continue
            rel = path.relative_to(REPO).as_posix()
            violations += personal_path_violations(rel, path.read_text(encoding="utf-8"), install_doc=rel in install_docs)
        self.assertEqual(violations, [])

    def test_codex_docs_keep_personal_install_and_identify_claude_schema(self):
        docs = [
            REPO / "README.md",
            REPO / ".codex-plugin" / "README.md",
            REPO / "docs" / "troubleshooting.md",
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO)
            self.assertIn("codex plugin add agentic-sdlc@personal", text, f"{rel} missing personal install")
            self.assertIn("codex plugin marketplace add", text, f"{rel} missing Codex catalog CLI")
            self.assertIn(".claude-plugin/marketplace.json", text, f"{rel} missing Claude marketplace path")
            self.assertRegex(
                text,
                r"Claude(?:'s)? marketplace schema",
                f"{rel} must say the Claude marketplace is Claude schema",
            )

    def test_runtime_adapter_records_codex_hook_live_proof_drift(self):
        # Five independent whole-document `assertIn`s used to stand here - "0.142.0",
        # "0.154.0", "historical", "current binary", "transcript_path". Co-occurrence was all
        # they checked, so INVERTING the claim (calling 0.142.0 the current binary and 0.154.0
        # the historical probe) satisfied every one of them, and so did scattering the two
        # version numbers into unrelated sections.
        #
        # The claim is directional, so the check is too: the version next to "current binary"
        # must not be the version next to "Historical", and each must be the expected one.
        # Bump both literals deliberately when the observed binary changes - that edit is the
        # point, the same way a digest lock is bumped in the commit that changes the file.
        text = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        # Scoped by the QUALIFIER, not by the line. Two line-based attempts were wrong: the
        # first line mentioning "current binary" is the section heading and carries no version,
        # and the sentence that does carry it states BOTH claims - so the first version on the
        # "historical" line was the current one.
        def version_after(word):
            match = re.search(word + r".{0,120}?(\d+\.\d+\.\d+)", text, re.IGNORECASE)
            return match.group(1) if match else None

        current = version_after(r"current binary")
        historical = version_after(r"historical\b")
        self.assertIsNotNone(current, "runtime-adapter.md names no current binary version")
        self.assertIsNotNone(historical, "runtime-adapter.md names no historical probe version")

        self.assertNotEqual(
            current, historical,
            "the current binary and the historical probe are recorded as the same version, so "
            "the drift this row exists to pin is not stated",
        )
        self.assertEqual(current, "0.160.1",
                         "current binary drifted; update this literal in the same commit")
        self.assertEqual(historical, "0.154.0",
                         "historical probe version drifted; update this literal in the same "
                         "commit")
        self.assertIn("transcript_path", text)
        self.assertIn("transcript_path", text)

    def test_claude_plugin_declares_display_name(self):
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin.get("displayName"), "Agentic SDLC")

    def test_codex_interface_meets_public_listing_limits(self):
        # Official Codex directory listing limits (developers.openai.com/plugins/deploy/submission-errors):
        # displayName and shortDescription <= 30, longDescription <= 4000, category exactly
        # `Developer Tools`, <= 3 defaultPrompt entries of <= 128 characters, brandColorDark contrast.
        field_limit_violations = {
            "display_name_too_long",
            "short_description_too_long",
            "long_description_too_long",
            "category_not_developer_tools",
            "too_many_default_prompts",
            "default_prompt_too_long",
            "brand_color_dark_format",
            "brand_color_dark_contrast",
        }
        manifest = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        violations = listing_violations(manifest, load_link_record(LINK_RECORD), REPO)
        self.assertEqual(sorted(set(violations) & field_limit_violations), [])
        prompts = manifest["interface"]["defaultPrompt"]
        normalized = [re.sub(r"\s+", " ", p.strip()) for p in prompts]
        self.assertEqual(len(normalized), len(set(normalized)))
        for prompt in prompts:
            self.assertNotIn("@", prompt)

    def test_codex_manifest_uses_publishable_schema_keys(self):
        codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        allowed_keys = {
            "id",
            "name",
            "version",
            "description",
            "skills",
            "hooks",
            "apps",
            "mcpServers",
            "interface",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
        }
        self.assertEqual(set(codex_plugin) - allowed_keys, set())

    def test_local_agent_instruction_files_are_not_tracked_plugin_payload(self):
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        tracked = set(proc.stdout.splitlines())
        self.assertNotIn("AGENTS.md", tracked)
        self.assertNotIn("CLAUDE.md", tracked)

    def test_plugin_components_do_not_depend_on_local_agent_instruction_files(self):
        component_roots = [
            ".claude-plugin",
            ".codex-plugin",
            "agents",
            "commands",
            "contracts",
            "hooks",
            "skills",
            "workflows",
        ]
        checked_suffixes = {".json", ".js", ".md", ".mjs", ".py"}
        forbidden = ("AGENTS.md", "CLAUDE.md")
        findings = []
        for root_name in component_roots:
            root = REPO / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in checked_suffixes:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for token in forbidden:
                    if token in text:
                        findings.append(f"{path.relative_to(REPO)} references {token}")
        self.assertEqual(findings, [])

    def test_plugin_components_do_not_hardcode_legacy_skill_creator_path(self):
        component_roots = [
            ".claude-plugin",
            ".codex-plugin",
            "agents",
            "commands",
            "contracts",
            "hooks",
            "skills",
            "workflows",
        ]
        checked_suffixes = {".json", ".js", ".md", ".mjs", ".py"}
        legacy_path = "/".join(
            (
                "~",
                ".claude",
                "plugins",
                "marketplaces",
                "anthropic-agent-skills",
                "skills",
                "skill-creator",
            )
        )
        findings = []
        for root_name in component_roots:
            root = REPO / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in checked_suffixes:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if legacy_path in text:
                    findings.append(f"{path.relative_to(REPO)} references legacy skill-creator path")
        self.assertEqual(findings, [])

    def test_version_check_script_passes(self):
        proc = subprocess.run(
            [sys.executable, "scripts/bump_version.py", "--check"],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("version_check=passed", proc.stdout)


def _link_entry(url, http_status=200, auth="none", **extra):
    return {"url": url, "checked_at": "2026-09-15T08:00:00Z", "http_status": http_status, "auth": auth, **extra}


def _top_level_record(manifest, repository_status=404):
    # One entry per distinct top-level URL; homepage and repository share one entry.
    urls = top_level_urls(manifest)
    record = []
    for url in sorted(set(urls.values())):
        status = repository_status if url == urls.get("repository") else 200
        record.append(_link_entry(url, http_status=status))
    return record


class TestLinkCheckRecord(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

    def test_record_schema_and_top_level_entries(self):
        record = load_link_record(LINK_RECORD)
        self.assertIsInstance(record, list)
        self.assertEqual(link_record_file_violations(LINK_RECORD.read_bytes()), [])
        self.assertEqual(link_record_violations(record, self.manifest), [])
        for field, url in top_level_urls(self.manifest).items():
            self.assertIsNotNone(record_entry(record, url), f"no link-check entry for top-level {field}")

    def test_record_schema_rejects_malformed_entries(self):
        repository = self.manifest["repository"]
        base = _top_level_record(self.manifest)
        self.assertEqual(link_record_violations(base, self.manifest), [])

        def replace_repository(**changes):
            return [dict(e, **changes) if e["url"] == repository else e for e in base]

        cases = {
            "entry_keys": replace_repository(note="x"),
            "auth_not_none": replace_repository(auth="basic"),
            "http_status_invalid": replace_repository(http_status="404"),
            "maintainer_decision_date": replace_repository(
                maintainer_decision={"decided_on": "soon", "maintainer_reference": "https://github.com/MrBekoX/agentic-sdlc/issues/1"}
            ),
            "maintainer_reference_not_https": replace_repository(
                maintainer_decision={"decided_on": "2026-09-01", "maintainer_reference": "http://x"}
            ),
            "duplicate_url": base + [_link_entry(repository, http_status=404)],
            "top_level_url_unrecorded": [e for e in base if e["url"] != self.manifest["author"]["url"]],
        }
        cases_trailing_slash = replace_repository(url=repository + "/")
        for name, record in cases.items():
            with self.subTest(name):
                self.assertIn(name, link_record_violations(record, self.manifest))
        with self.subTest("repository entry with trailing slash"):
            self.assertIn("top_level_url_unrecorded", link_record_violations(cases_trailing_slash, self.manifest))
        with self.subTest("repository entry at 404 is recorded, not a violation"):
            self.assertEqual(link_record_violations(replace_repository(http_status=404), self.manifest), [])
        with self.subTest("checked_at with a trailing newline"):
            record = replace_repository(checked_at="2026-09-15T08:00:00Z\n")
            self.assertIn("checked_at_invalid", link_record_violations(record, self.manifest))
        with self.subTest("decided_on with a trailing newline"):
            decision = {"decided_on": "2026-09-01\n", "maintainer_reference": "https://github.com/MrBekoX/agentic-sdlc/issues/1"}
            record = replace_repository(maintainer_decision=decision)
            self.assertIn("maintainer_decision_date", link_record_violations(record, self.manifest))

    def test_record_file_contract_synthetic(self):
        # Task 2 file contract: sorted by url, LF only, trailing newline.
        base = _top_level_record(self.manifest)
        lf = (json.dumps(base, indent=2) + "\n").encode("utf-8")
        self.assertEqual(link_record_file_violations(lf), [])
        cases = {
            "record_not_lf": lf.replace(b"\n", b"\r\n"),
            "record_no_trailing_newline": lf.rstrip(b"\n"),
            "record_not_sorted_by_url": (json.dumps(list(reversed(base)), indent=2) + "\n").encode("utf-8"),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertIn(name, link_record_file_violations(raw))


URL_VIOLATIONS = {
    "terms_of_service_present",
    "third_party_policy_page",
    "license_as_policy",
    "empty_url",
    "non_https",
    "unchecked_link",
    "not_product_owned",
    "top_level_url_unrecorded",
}


class TestListingRules(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.record = _top_level_record(self.manifest)
        # Synthetic base: the real manifest without interface URLs or screenshots.
        self.base = copy.deepcopy(self.manifest)
        for key in [k for k in self.base["interface"] if k.endswith("URL") or k == "screenshots"]:
            del self.base["interface"][key]

    def with_interface(self, **changes):
        manifest = copy.deepcopy(self.base)
        manifest["interface"].update(changes)
        return manifest

    def test_interface_policy_link_rules(self):
        real = listing_violations(self.manifest, load_link_record(LINK_RECORD), REPO)
        self.assertEqual(sorted(set(real) & URL_VIOLATIONS), [])
        data_handling = "https://github.com/MrBekoX/agentic-sdlc/blob/main/docs/data-handling.md"
        cases = [
            ("terms_of_service_present", {"termsOfServiceURL": "https://github.com/MrBekoX/agentic-sdlc/blob/main/TERMS.md"}, self.record),
            (
                "third_party_policy_page",
                {"privacyPolicyURL": "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement"},
                self.record,
            ),
            ("license_as_policy", {"privacyPolicyURL": "https://github.com/MrBekoX/agentic-sdlc/blob/main/LICENSE"}, self.record),
            ("empty_url", {"privacyPolicyURL": ""}, self.record),
            ("non_https", {"privacyPolicyURL": "http://github.com/MrBekoX/agentic-sdlc/blob/main/docs/data-handling.md"}, self.record),
            ("unchecked_link", {"privacyPolicyURL": data_handling}, self.record),
            ("unchecked_link", {"privacyPolicyURL": data_handling}, self.record + [_link_entry(data_handling, http_status=404)]),
            ("unchecked_link", {"privacyPolicyURL": data_handling}, self.record + [_link_entry(data_handling, auth="basic")]),
            ("unchecked_link", {"privacyPolicyURL": data_handling}, self.record + [_link_entry(data_handling + "/")]),
            (
                "not_product_owned",
                {"privacyPolicyURL": "https://example.org/privacy"},
                self.record + [_link_entry("https://example.org/privacy")],
            ),
        ]
        for name, changes, record in cases:
            with self.subTest(name=name, changes=changes, entries=len(record)):
                self.assertIn(name, listing_violations(self.with_interface(**changes), record, REPO))

    def test_interface_website_url_rules(self):
        repository = self.manifest["repository"]
        self.assertIn("unchecked_link", listing_violations(self.with_interface(websiteURL=repository), self.record, REPO))
        other = "https://github.com/MrBekoX/agentic-sdlc-x"
        undecided = self.record + [_link_entry(other)]
        self.assertIn("not_product_owned", listing_violations(self.with_interface(websiteURL=other), undecided, REPO))
        decision = {"decided_on": "2026-09-01", "maintainer_reference": "https://github.com/MrBekoX/agentic-sdlc/issues/1"}
        decided = self.record + [_link_entry(other, maintainer_decision=decision)]
        self.assertEqual(listing_violations(self.with_interface(websiteURL=other), decided, REPO), [])
        without_author = [e for e in self.record if e["url"] != self.manifest["author"]["url"]]
        self.assertIn("top_level_url_unrecorded", listing_violations(self.base, without_author, REPO))
        self.assertEqual(record_entry(self.record, repository)["http_status"], 404)
        self.assertEqual(listing_violations(self.base, self.record, REPO), [])

    def test_interface_has_no_screenshots_key(self):
        self.assertNotIn("screenshots", self.manifest["interface"])
        self.assertIn("screenshots_present", listing_violations(self.with_interface(screenshots=[]), self.record, REPO))

    def test_listing_field_limits_edge_values(self):
        accepted = {
            "displayName of 30": {"displayName": "D" * 30},
            "longDescription of 4000": {"longDescription": "L" * 4000},
            "defaultPrompt entry of 128": {"defaultPrompt": ["P" * 128]},
            "3 defaultPrompt entries": {"defaultPrompt": ["First prompt.", "Second prompt.", "Third prompt."]},
            "brandColorDark #FFFFFF": {"brandColorDark": "#FFFFFF"},
        }
        for label, changes in accepted.items():
            with self.subTest(label):
                self.assertEqual(listing_violations(self.with_interface(**changes), self.record, REPO), [])
        rejected = [
            ("display_name_too_long", {"displayName": "D" * 31}),
            ("short_description_too_long", {"shortDescription": "S" * 31}),
            ("long_description_too_long", {"longDescription": "L" * 4001}),
            ("default_prompt_too_long", {"defaultPrompt": ["P" * 129]}),
            ("too_many_default_prompts", {"defaultPrompt": ["One.", "Two.", "Three.", "Four."]}),
            ("category_not_developer_tools", {"category": "Developer tools"}),
            ("category_not_developer_tools", {"category": "Productivity"}),
            ("brand_color_dark_contrast", {"brandColorDark": "#333333"}),
        ]
        for name, changes in rejected:
            with self.subTest(name=name, changes=changes):
                self.assertIn(name, listing_violations(self.with_interface(**changes), self.record, REPO))

    def test_asset_rules_edge_geometry(self):
        def png(width, height):
            # Signature, IHDR length and type, then big-endian width/height at offsets 16-24.
            return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets" / "icon.png").write_bytes(png(48, 48))
            interface = {"composerIcon": "./assets/icon.png", "logo": "./assets/logo.png"}
            for width, height in ((48, 48), (4096, 4096)):
                with self.subTest(accepted=(width, height)):
                    (root / "assets" / "logo.png").write_bytes(png(width, height))
                    self.assertEqual(asset_violations(interface, root), [])
            for width, height in ((4097, 4097), (256, 255), (47, 47)):
                with self.subTest(rejected=(width, height)):
                    (root / "assets" / "logo.png").write_bytes(png(width, height))
                    self.assertIn("asset_geometry", asset_violations(interface, root))
            with self.subTest("escaping path"):
                escaping = dict(interface, logo="./assets/../../outside.png")
                self.assertIn("asset_outside_package", asset_violations(escaping, root))
            with self.subTest("jpeg bytes"):
                (root / "assets" / "logo.png").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 40)
                self.assertIn("asset_not_png", asset_violations(interface, root))
            with self.subTest("missing file"):
                (root / "assets" / "logo.png").unlink()
                self.assertIn("asset_missing", asset_violations(interface, root))

        real = self.manifest["interface"]
        self.assertEqual(asset_violations(real, REPO), [])
        logo = (REPO / real["logo"]).read_bytes()
        self.assertGreaterEqual(struct.unpack(">II", logo[16:24])[0], 48)

    def test_brand_color_contrast_against_white(self):
        real = listing_violations(self.manifest, load_link_record(LINK_RECORD), REPO)
        self.assertEqual([v for v in real if v.startswith("brand_color_")], [])
        self.assertAlmostEqual(contrast_ratio("#58DBC0", "#FFFFFF"), 1.71, delta=0.01)
        self.assertIn("brand_color_contrast", listing_violations(self.with_interface(brandColor="#58DBC0"), self.record, REPO))
        self.assertAlmostEqual(contrast_ratio("#20806E", "#FFFFFF"), 4.80, delta=0.01)
        for accepted in ("#20806E", "#20806e"):
            with self.subTest(accepted):
                violations = listing_violations(self.with_interface(brandColor=accepted), self.record, REPO)
                self.assertEqual([v for v in violations if v.startswith("brand_color_")], [])
        for malformed in ("#2a8", "#GGGGGG", "#20806E\n"):
            with self.subTest(malformed):
                self.assertIn("brand_color_format", listing_violations(self.with_interface(brandColor=malformed), self.record, REPO))

    def test_codex_manifest_format_rule_synthetic(self):
        portable_hooks = dict(self.manifest, hooks="./hooks/hooks.json")
        self.assertIn("hooks_not_legacy_codex", codex_manifest_format_violations(portable_hooks))
        no_skills = {k: v for k, v in self.manifest.items() if k != "skills"}
        self.assertIn("skills_not_declared", codex_manifest_format_violations(no_skills))
        self.assertEqual(codex_manifest_format_violations(self.manifest), [])


class TestVersionDeclarations(unittest.TestCase):
    README = "# agentic-sdlc\n\n> `Version 0.4.3` - `MIT` - `Author: Beko`\n\n## Versioning\n\nCurrent version: `0.4.3`.\n"
    PLUGIN_README = "# Plugin reference\n\n> Version: `0.4.3`. This is the component-by-component reference.\n"
    RELEASE_READINESS = (
        "# Release Readiness\n\nThis file is the publish gate for `agentic-sdlc` version `0.4.3`. "
        "It keeps the release decision evidence-based.\n"
        "\n## Release Verdict Template\n\n```text\nversion=0.4.3\nscope=Claude Code, Codex\n```\n"
    )
    MANIFESTS = {
        ".claude-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
        ".claude-plugin/marketplace.json": {"plugins": [{"name": "agentic-sdlc", "version": "0.4.3"}]},
        ".codex-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
    }

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bump_version_under_test", REPO / "scripts" / "bump_version.py")
        cls.bump_version = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bump_version)

    def write_tree(self, root, readme=None, plugin_readme=None, release_readiness=None, manifests=None):
        manifest_data = {**self.MANIFESTS, **(manifests or {})}
        files = {
            "VERSION": "0.4.3\n",
            **{rel: json.dumps(data) + "\n" for rel, data in manifest_data.items()},
            "README.md": self.README if readme is None else readme,
            "docs/plugin-readme.md": self.PLUGIN_README if plugin_readme is None else plugin_readme,
            "docs/release-readiness.md": self.RELEASE_READINESS if release_readiness is None else release_readiness,
            "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n## 0.4.3 - 2026-09-14\n\n- Publication readiness.\n",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            # LF on every host: the (?m)^ anchors must not see a stray \r.
            path.write_text(text, encoding="utf-8", newline="\n")

    def run_check(self, release=False, readme=None, plugin_readme=None, release_readiness=None, manifests=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, readme, plugin_readme, release_readiness, manifests)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.check(release=release, root=root)
        return code, out.getvalue()

    def test_bump_rewrites_every_declaration_then_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.bump("0.4.4", root=root)
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("version_check=passed", out.getvalue())
            self.assertEqual((root / "VERSION").read_bytes(), b"0.4.4\n")
            template = (root / "docs" / "release-readiness.md").read_bytes()
            self.assertRegex(template, rb"(?m)^version=0\.4\.4\n")
            self.assertNotIn(b"0.4.3", template)
            self.assertIn(b"scope=Claude Code, Codex\n", template)
            readme = (root / "README.md").read_bytes()
            self.assertIn(b"> `Version 0.4.4` - `MIT`", readme)
            self.assertIn(b"Current version: `0.4.4`.", readme)
            self.assertIn(b"> Version: `0.4.4`.", (root / "docs" / "plugin-readme.md").read_bytes())
            for rel in self.MANIFESTS:
                data = (root / rel).read_bytes()
                self.assertNotIn(b"\r", data, rel)
                self.assertIn(b'"version": "0.4.4"', data, rel)

    def test_bump_rejects_non_release_version_before_writing(self):
        # The verdict template line only admits X.Y.Z; a pre-release or build bump would
        # strand it (version_missing forever), so bump must refuse before touching the tree.
        for version in ("0.5.0-rc1", "0.5.0+build.7"):
            with self.subTest(version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_tree(root)
                before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = self.bump_version.bump(version, root=root)
                self.assertEqual(code, 2, out.getvalue())
                self.assertIn(f"error=unsupported_version:{version}", out.getvalue())
                after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                self.assertEqual(after, before)

    def test_manifest_version_drift_fails(self):
        cases = {
            "plugin 0.4.2": (".claude-plugin/plugin.json", {"name": "agentic-sdlc", "version": "0.4.2"}),
            "plugin missing": (".claude-plugin/plugin.json", {"name": "agentic-sdlc"}),
            "marketplace 0.4.2": (".claude-plugin/marketplace.json", {"plugins": [{"name": "agentic-sdlc", "version": "0.4.2"}]}),
            "marketplace missing": (".claude-plugin/marketplace.json", {"plugins": [{"name": "agentic-sdlc"}]}),
            "codex 0.4.2": (".codex-plugin/plugin.json", {"name": "agentic-sdlc", "version": "0.4.2"}),
            "codex missing": (".codex-plugin/plugin.json", {"name": "agentic-sdlc"}),
        }
        for label, (rel, data) in cases.items():
            with self.subTest(label):
                code, out = self.run_check(manifests={rel: data})
                self.assertEqual(code, 1, out)
                self.assertIn(f"version_mismatch={rel}:version:", out)
                self.assertIn("version_check=failed", out)

    ADAPTER_MANIFESTS = {
        ".kimi-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
        ".zcode-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
        "marketplace.json": {"name": "mrbekox", "plugins": [{"name": "agentic-sdlc", "version": "0.4.3"}]},
        ".grok-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
        ".grok-plugin/marketplace.json": {"name": "mrbekox", "plugins": [{"name": "agentic-sdlc", "version": "0.4.3"}]},
    }

    def test_adapter_manifest_drift_fails_like_the_release_manifests(self):
        # Before this, ZCode and Grok versions were pinned only by their own packaging tests, so a
        # bump that forgot them drifted until one of those tests happened to run.
        for rel, data in self.ADAPTER_MANIFESTS.items():
            stale = json.loads(json.dumps(data))
            if "plugins" in stale:
                stale["plugins"][0]["version"] = "0.4.2"
            else:
                stale["version"] = "0.4.2"
            with self.subTest(rel):
                code, out = self.run_check(manifests={**self.ADAPTER_MANIFESTS, rel: stale})
                self.assertEqual(code, 1, out)
                self.assertIn(f"version_mismatch={rel}:version:0.4.2", out)

    def test_an_absent_adapter_manifest_is_not_drift(self):
        # The skills-only archive and any future adapter removal leave these files out.
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        for rel in self.ADAPTER_MANIFESTS:
            with self.subTest(rel):
                self.assertNotIn(f"version_mismatch={rel}", out)

    def test_bump_writes_every_present_manifest_including_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, manifests=self.ADAPTER_MANIFESTS)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.bump("0.4.4", root=root)
            self.assertEqual(code, 0, out.getvalue())
            for rel in {**self.MANIFESTS, **self.ADAPTER_MANIFESTS}:
                with self.subTest(rel):
                    self.assertIn(b'"version": "0.4.4"', (root / rel).read_bytes(), rel)

    def test_audit_reports_a_manifest_the_version_gate_does_not_cover(self):
        # The failure this catches: a new runtime adapter ships a manifest, nothing registers it,
        # and the next bump leaves it on the old version.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, manifests=self.ADAPTER_MANIFESTS)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.audit(root=root)
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("audit=passed", out.getvalue())

            unregistered = root / ".newharness-plugin" / "plugin.json"
            unregistered.parent.mkdir(parents=True, exist_ok=True)
            unregistered.write_text(json.dumps({"name": "agentic-sdlc", "version": "0.4.3"}) + "\n",
                                    encoding="utf-8", newline="\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.audit(root=root)
            self.assertEqual(code, 1, out.getvalue())
            self.assertIn("audit_manifest=.newharness-plugin/plugin.json:unregistered", out.getvalue())
            self.assertIn("audit=failed", out.getvalue())

    def test_kimi_bump_preserves_marketplace_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, manifests=self.ADAPTER_MANIFESTS)
            marketplace = root / "marketplace-kimi.json"
            marketplace.write_text('{"version":"2","plugins":[{"id":"agentic-sdlc","source":"https://github.com/MrBekoX/agentic-sdlc"}]}\n', encoding="utf-8")
            before = marketplace.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.bump_version.bump("0.4.4", root=root)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((root / ".kimi-plugin/plugin.json").read_bytes())["version"], "0.4.4")
            self.assertEqual(marketplace.read_bytes(), before)

    def test_audit_discovers_named_marketplace_plugin_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root)
            marketplace = root / "marketplace-new-runtime.json"
            marketplace.write_text('{"version":"2","plugins":[{"id":"agentic-sdlc","version":"0.4.3"}]}', encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.audit(root=root)
            self.assertEqual(code, 1, out.getvalue())
            self.assertIn("audit_manifest=marketplace-new-runtime.json:unregistered", out.getvalue())

    def test_audit_ignores_test_fixtures_and_untracked_scratch_trees(self):
        # The walk fallback runs here (a temp dir is not a git repository), so the prune list is
        # what keeps another project's manifests out of this project's audit.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root)
            fixture = root / "tests" / "fixtures" / "plugin.json"
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(json.dumps({"name": "fixture", "version": "9.9.9"}) + "\n",
                               encoding="utf-8", newline="\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.bump_version.audit(root=root)
            self.assertEqual(code, 0, out.getvalue())
            self.assertNotIn("tests/fixtures", out.getvalue())

    def test_verdict_template_version_drift_fails(self):
        stale = self.RELEASE_READINESS.replace("\nversion=0.4.3\n", "\nversion=0.4.2\n")
        self.assertNotEqual(stale, self.RELEASE_READINESS)
        code, out = self.run_check(release_readiness=stale)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^version_mismatch=docs/release-readiness\.md:verdict-template-version:0\.4\.2$")
        self.assertIn("version_check=failed", out)
        missing = self.RELEASE_READINESS.replace("\nversion=0.4.3\n", "\n")
        code, out = self.run_check(release_readiness=missing)
        self.assertEqual(code, 1, out)
        self.assertIn("version_missing=docs/release-readiness.md:verdict-template-version", out)

    def test_stale_current_version_sentence_fails(self):
        code, out = self.run_check(readme=self.README.replace("Current version: `0.4.3`.", "Current version: `0.4.2`."))
        self.assertEqual(code, 1, out)
        self.assertIn("README.md", out)
        self.assertIn("0.4.2", out)
        self.assertIn("version_check=failed", out)

    def test_declaration_edge_cases(self):
        badge = "> `Version 0.4.3` - `MIT` - `Author: Beko`\n"
        cases = {
            "sentence missing": {"readme": self.README.replace("Current version: `0.4.3`.\n", "")},
            "sentence 0.4.3-rc1": {"readme": self.README.replace("`0.4.3`.", "`0.4.3-rc1`.")},
            "whitespace inside backticks": {"readme": self.README.replace("`0.4.3`.", "` 0.4.3`.")},
            "two differing version tokens": {"readme": self.README + "\nSee `Version 0.4.2` notes.\n"},
            "version token only mid-line": {"readme": self.README.replace(badge, "Release `Version 0.4.3` - `MIT`\n")},
            "plugin-readme 0.4.2": {"plugin_readme": self.PLUGIN_README.replace("`0.4.3`", "`0.4.2`")},
            "plugin-readme line missing": {"plugin_readme": "# Plugin reference\n\nNo version line.\n"},
            "release-readiness 0.4.2": {"release_readiness": self.RELEASE_READINESS.replace("`0.4.3`", "`0.4.2`")},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                code, out = self.run_check(**overrides)
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^version_(?:mismatch|missing)=")
                self.assertIn("version_check=failed", out)

    def test_historical_version_text_is_not_a_declaration(self):
        history = (
            "\n## Historical evidence\n\nPlugin cache refreshed to `agentic-sdlc@personal` version `0.3.0` before the run.\n"
            "\n```text\nprevious version=0.4.2\n```\n"
        )
        code, out = self.run_check(release_readiness=self.RELEASE_READINESS + history)
        self.assertEqual(code, 0, out)

    def test_all_declarations_match_passes(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("version_check=passed", out)
        code, out = self.run_check(release=True)
        self.assertEqual(code, 0, out)
        self.assertIn("release_check=passed", out)
        self.assertIn("version_check=passed", out)

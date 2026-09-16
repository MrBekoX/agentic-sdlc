"""Build, verify and history-scan agentic-sdlc distribution archives.

Three fixed modes (spec public interface):
  --output <zip> [--skills-only]  build the release archive, or the BR24 skills-only archive,
                                  from the tree of the recorded HEAD commit; worktree bytes never
                                  enter an archive.
  --verify <zip>                  verify an archive against its recorded source commit.
  --scan-history <mirror>         scan every ref of a local bare mirror for secrets and private paths.

Output convention for all modes: key=value lines, error=<code>:<detail> lines; exit 0 pass,
1 check failure, 2 usage or environment error.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

try:
    from scripts.eval_safety import require_relative_pattern
except ModuleNotFoundError:
    from eval_safety import require_relative_pattern


# BR13 exclusion classes. A member in any class never enters an archive.
EXCLUSION_CLASSES = {
    1: "maintainer prompts (agentic-sdlc-prompts/**)",
    2: "private eval prompt test (tests/test_superpowers_referenced_eval_prompt.py)",
    3: "local agent instructions (AGENTS.md, CLAUDE.md)",
    4: "user settings (.claude/, .codex/, settings.local.json, .env, .env.*)",
    5: "raw transcripts (tests/artifacts/**)",
    6: "audit dumps (audit-docs/**, .handoffs/**)",
    7: "unsafe member (symlink, absolute, '..', backslash)",
}

_SYMLINK_MODE = 0o120000
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_GIT_ENV_DROP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _is_symlink_mode(mode) -> bool:
    if isinstance(mode, str):
        try:
            mode = int(mode, 8)
        except ValueError:
            return False
    return stat.S_IFMT(int(mode)) == _SYMLINK_MODE


def _has_unsafe_character(path: str) -> bool:
    """A control character, DEL or a lone surrogate (an undecodable git path byte)."""
    return any(ch < " " or ch == "\x7f" or "\ud800" <= ch <= "\udfff" for ch in path)


def _is_unsafe_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or _DRIVE_PREFIX.match(path):
        return True
    if ".." in path.split("/") or _has_unsafe_character(path):
        return True
    try:
        require_relative_pattern(path, "archive member")
    except ValueError:
        return True
    return False


def _display_path(path: str) -> str:
    """The path as printed on a result line: escaped when it holds an unsafe character (SEC-13)."""
    return path.encode("unicode_escape").decode("ascii") if _has_unsafe_character(path) else path


def exclusion_class(path: str, mode) -> int | None:
    """Return the BR13 exclusion class (1..7) of a member path and git mode, or None.

    Classes 1-6 compare case-folded segments with trailing dots and spaces stripped, because a
    case-insensitive filesystem (NTFS, APFS) opens those spellings as the excluded file (SEC-8).
    """
    if _is_symlink_mode(mode) or _is_unsafe_path(path):
        return 7
    parts = [part.casefold().rstrip(". ") for part in path.split("/")]
    base = parts[-1]
    if parts[0] == "agentic-sdlc-prompts":
        return 1
    if parts == ["tests", "test_superpowers_referenced_eval_prompt.py"]:
        return 2
    if base in ("agents.md", "claude.md"):
        return 3
    if (
        any(part in (".claude", ".codex") for part in parts[:-1])
        or base == "settings.local.json"
        or ((base == ".env" or base.startswith(".env.")) and base != ".env.example")
    ):
        return 4
    if parts[:2] == ["tests", "artifacts"]:
        return 5
    if parts[0] in ("audit-docs", ".handoffs"):
        return 6
    return None


_ABSOLUTE_WINDOWS_ENTRY = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")


def _program_on_absolute_path(name: str) -> str | None:
    """The first candidate for name in an absolute PATH entry, or None (D25 model 5).

    A current directory or relative PATH entry is never searched. On win32 only <name>.exe and
    <name>.com are tried (PATHEXT is not consulted, so no batch file starts without a shell);
    elsewhere a candidate must be an executable regular file.
    """
    windows = sys.platform == "win32"
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if windows:
            if not _ABSOLUTE_WINDOWS_ENTRY.match(entry):
                continue
            candidates = [os.path.join(entry, name + suffix) for suffix in (".exe", ".com")]
        else:
            if not entry.startswith("/"):
                continue
            candidates = [os.path.join(entry, name)]
        for candidate in candidates:
            if os.path.isfile(candidate) and (windows or os.access(candidate, os.X_OK)):
                return candidate
    return None


def _run_git(args, *, git_dir=None, cwd=None, stdin=None) -> subprocess.CompletedProcess:
    """Run one local git command: fixed argv, no shell, no protocol, no fsmonitor, bytes I/O."""
    git = _program_on_absolute_path("git")
    if git is None:
        raise ReleaseError(["error=git_not_found"], exit_code=2)
    argv = [git, "-c", "protocol.allow=never", "-c", "core.fsmonitor=false"]
    if git_dir is not None:
        argv += ["--git-dir", str(git_dir)]
    argv += [str(a) for a in args]
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, env=env)


ARCHIVE_COMMENT_PREFIX = b"agentic-sdlc-archive source_commit="
# BR20: the runtime payload identity covers every release member except the two result ledgers.
# The versioned ledger name follows the VERSION file next to scripts/ (QUAL-8).
_RELEASE_VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
RUNTIME_PAYLOAD_EXCLUDE = frozenset({f"docs/release-evidence-{_RELEASE_VERSION}.md", "docs/release-readiness.md"})
# BR24: the skills-only archive holds exactly these committed roots plus LICENSE.
SKILLS_ONLY_ROOTS = (".codex-plugin/", "skills/", "hooks/", "contracts/skills/", "scripts/", "assets/")
CODEX_MANIFEST = ".codex-plugin/plugin.json"


class ReleaseError(Exception):
    """A named failure carrying the error= lines to print and the exit code."""

    def __init__(self, lines, exit_code: int = 1):
        super().__init__("; ".join(lines))
        self.lines = list(lines)
        self.exit_code = exit_code


@dataclass
class BuildResult:
    exit_code: int
    lines: list = field(default_factory=list)


class _Emitter:
    """Print key=value lines as they are produced and keep them in order."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)
        print(line, flush=True)


def _git_ok(args, **kwargs) -> bytes:
    proc = _run_git(args, **kwargs)
    if proc.returncode != 0:
        raise ReleaseError([f"error=git_failed:{args[0]}"], exit_code=2)
    return proc.stdout


def _resolve_head_commit(repo_root: Path) -> str:
    _git_ok(["rev-parse", "--show-toplevel"], cwd=repo_root)
    return _git_ok(["rev-parse", "--verify", "HEAD^{commit}"], cwd=repo_root).decode("ascii").strip()


def _tree_entries(commit: str, **git) -> list:
    """(mode, type, oid, path) for every entry of the commit tree, recursively."""
    entries = []
    for record in _git_ok(["ls-tree", "-r", "-z", "--full-tree", commit], **git).split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, otype, oid = meta.decode("ascii").split(" ")
        entries.append((mode, otype, oid, path.decode("utf-8", "surrogateescape")))
    return entries


def _read_objects(oids, **git) -> dict:
    """Read object contents through one 'cat-file --batch' process."""
    unique = list(dict.fromkeys(oids))
    if not unique:
        return {}
    out = _git_ok(["cat-file", "--batch"], stdin="".join(o + "\n" for o in unique).encode("ascii"), **git)
    objects, pos = {}, 0
    for oid in unique:
        header_end = out.index(b"\n", pos)
        header = out[pos:header_end].decode("ascii").split(" ")
        if len(header) != 3:
            raise ReleaseError([f"error=object_unavailable:{oid}"], exit_code=2)
        start = header_end + 1
        size = int(header[2])
        objects[oid] = out[start:start + size]
        pos = start + size + 1
    return objects


def _collisions(paths) -> list:
    """error=case_collision lines for members one extraction filesystem path maps together (SEC-9).

    The key is the NFC form, case-folded, with trailing dots and spaces stripped from each segment.
    Two clashes count: equal full keys, and a file key equal to another member's directory prefix.
    Each pair is printed in UTF-8 order.
    """
    def order(path: str) -> bytes:
        return path.encode("utf-8", "surrogateescape")

    keys = {
        path: tuple(part.casefold().rstrip(". ") for part in unicodedata.normalize("NFC", path).split("/"))
        for path in sorted(set(paths), key=order)
    }
    owners = {}
    lines = []
    for path, key in keys.items():
        other = owners.setdefault(key, path)
        if other != path:
            lines.append((order(other), order(path), other, path))
    for path, key in keys.items():
        for end in range(1, len(key)):
            other = owners.get(key[:end])
            if other is not None:
                first, second = sorted((other, path), key=order)
                lines.append((order(first), order(second), first, second))
    return [f"error=case_collision:{_display_path(a)}:{_display_path(b)}" for _ka, _kb, a, b in sorted(lines)]


def _commit_members(commit: str, *, cwd: Path) -> dict:
    """BR13-filtered members of the commit tree: path -> (git mode, bytes)."""
    entries = _tree_entries(commit, cwd=cwd)
    violations = []
    for mode, _otype, _oid, path in entries:
        if mode == "160000":
            violations.append(f"error=unsupported_member:{_display_path(path)}")
            continue
        cls = exclusion_class(path, mode)
        if cls is not None:
            violations.append(f"error=excluded_member:class-{cls}:{_display_path(path)}")
    violations += _collisions([path for _mode, _otype, _oid, path in entries])
    if violations:
        raise ReleaseError(violations)
    blobs = _read_objects([oid for _m, _t, oid, _p in entries], cwd=cwd)
    return {path: (mode, blobs[oid]) for mode, _otype, oid, path in entries}


def _utf8_order(paths) -> list:
    return sorted(paths, key=lambda p: p.encode("utf-8"))


def release_members(repo_root, commit: str) -> dict:
    """BR13-filtered committed-tree members of the commit: path -> bytes (the build's member source)."""
    return {path: data for path, (_mode, data) in _commit_members(commit, cwd=Path(repo_root)).items()}


def payload_identity(members: dict, exclude: frozenset) -> str:
    """BR20 identity: SHA-256 of '<member sha256>  <path>\\n' lines in UTF-8 path order (sha256sum form)."""
    manifest = "".join(
        f"{hashlib.sha256(members[path]).hexdigest()}  {path}\n"
        for path in _utf8_order(members)
        if path not in exclude
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _zip_entry(path: str, mode: str) -> zipfile.ZipInfo:
    """Fixed, host-independent ZIP header fields; the mode comes from the git tree, never os.stat."""
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
    return info


def _zip_bytes(members: dict, commit: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.comment = ARCHIVE_COMMENT_PREFIX + commit.encode("ascii")
        for path in _utf8_order(members):
            mode, data = members[path]
            zf.writestr(_zip_entry(path, mode), data)
    return buf.getvalue()


def _write_atomic(output: Path, data: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output.parent, prefix=".build-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, output)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _select_skills_only(members: dict) -> dict:
    """BR24: the committed members under the skills-only roots plus LICENSE, with no MCP configuration."""
    selected = {p: v for p, v in members.items() if p == "LICENSE" or p.startswith(SKILLS_ONLY_ROOTS)}
    errors = [f"error=mcp_configuration:{p}" for p in _utf8_order(selected) if p.rsplit("/", 1)[-1] == ".mcp.json"]
    manifest = selected.get(CODEX_MANIFEST)
    if manifest is not None:
        try:
            declared = json.loads(manifest[1].decode("utf-8"))
        except ValueError:
            errors.append(f"error=manifest_unreadable:{CODEX_MANIFEST}")
        else:
            if isinstance(declared, dict) and "mcpServers" in declared:
                errors.append(f"error=mcp_configuration:{CODEX_MANIFEST}")
    if "LICENSE" not in selected:
        errors.append("error=missing_br24_member:LICENSE")
    if errors:
        raise ReleaseError(errors)
    return selected


def _kind_members(commit: str, *, cwd: Path, skills_only: bool) -> dict:
    members = _commit_members(commit, cwd=cwd)
    return _select_skills_only(members) if skills_only else members


def _identity_line(members: dict, skills_only: bool) -> str:
    data = {p: d for p, (_m, d) in members.items()}
    if skills_only:
        return "skills_only_payload_identity=" + payload_identity(data, frozenset())
    return "runtime_payload_identity=" + payload_identity(data, RUNTIME_PAYLOAD_EXCLUDE)


def build_archive(repo_root, output, *, skills_only: bool = False) -> BuildResult:
    """Build the release (or BR24 skills-only) archive from the recorded HEAD commit of repo_root."""
    emit = _Emitter()
    repo_root = Path(repo_root)
    try:
        commit = _resolve_head_commit(repo_root)
        members = _kind_members(commit, cwd=repo_root, skills_only=skills_only)
    except ReleaseError as exc:
        for line in exc.lines:
            emit(line)
        emit("build=failed")
        return BuildResult(exc.exit_code, emit.lines)
    data = _zip_bytes(members, commit)
    try:
        _write_atomic(Path(output), data)
    except OSError:
        emit("error=output_unwritable")
        emit("build=failed")
        return BuildResult(2, emit.lines)
    emit("archive_kind=" + ("skills-only" if skills_only else "release"))
    emit(f"source_commit={commit}")
    emit(f"members={len(members)}")
    emit("archive_sha256=" + hashlib.sha256(data).hexdigest())
    emit(_identity_line(members, skills_only))
    emit("build=passed")
    return BuildResult(0, emit.lines)


SECRET_PATTERNS_MODULE = Path(__file__).resolve().parents[1] / "hooks" / "secret-patterns.mjs"
BINARY_PROBE_BYTES = 8000

# BR22 bridge: the commit scanner's rules (scanLines over HIGH) stay the single implementation.
# Text arrives only on stdin as JSON lines; only line numbers, labels and reasons leave the bridge.
# A suppressed line is one scanLines does not report. A marked line that still has an unsuppressed match
# once its marker text is blanked is listed as allow-marker, with that match's label (D22: the marker is
# what suppresses it). Otherwise the reason follows the scanner's own order: an exact documentation
# sample, then a degenerate token, then a same-line allow marker.
_SCAN_BRIDGE = r"""
import { pathToFileURL } from 'node:url';
const { HIGH, scanLines, looksPlaceholder, ALLOW_MARKER, DOC_SAMPLES, isDegenerateToken } =
  await import(pathToFileURL(__PATTERNS__).href);
let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) input += chunk;
const out = [];
for (const raw of input.split('\n')) {
  if (!raw) continue;
  const { id, text } = JSON.parse(raw);
  const findings = scanLines(text, HIGH);
  const reported = new Set(findings.map((f) => f.line));
  const suppressed = [];
  String(text).split(/\r?\n/).forEach((line, i) => {
    if (reported.has(i + 1)) return;
    if (ALLOW_MARKER.test(line)) {
      const hidden = scanLines(line.replace(new RegExp(ALLOW_MARKER.source, 'gi'), ' '), HIGH);
      if (hidden.length) { suppressed.push({ line: i + 1, label: hidden[0].label, reason: 'allow-marker' }); return; }
    }
    for (const p of HIGH) {
      p.re.lastIndex = 0;
      const m = p.re.exec(line);
      if (!m) continue;
      if (p.valueGroup && looksPlaceholder(m[p.valueGroup])) continue;
      let reason = null;
      if (!p.valueGroup && DOC_SAMPLES.has(m[0])) reason = 'documentation-sample';
      else if (!p.valueGroup && isDegenerateToken(m[0])) reason = 'degenerate-token';
      else if (ALLOW_MARKER.test(line)) reason = 'allow-marker';
      if (reason) { suppressed.push({ line: i + 1, label: p.label, reason }); break; }
    }
  });
  out.push(JSON.stringify({ id, findings, suppressed }));
}
process.stdout.write(out.map((l) => l + '\n').join(''));
"""


CREDENTIAL_NAMES_MODULE = SECRET_PATTERNS_MODULE.parent / "scan-commit-names.mjs"
CREDENTIAL_FILENAME_LABEL = "credential-filename"

# SEC-12 bridge: the commit scanner's credential-filename rule stays the single implementation.
# Only member paths enter it, one JSON line each; only a boolean per id leaves it.
_NAME_BRIDGE = r"""
import { pathToFileURL } from 'node:url';
const { isCredentialFilename } = await import(pathToFileURL(__NAMES__).href);
let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) input += chunk;
const out = [];
for (const raw of input.split('\n')) {
  if (!raw) continue;
  const { id, path } = JSON.parse(raw);
  out.push(JSON.stringify({ id, credential: isCredentialFilename(path) === true }));
}
process.stdout.write(out.map((l) => l + '\n').join(''));
"""


class NodeUnavailable(Exception):
    """node is required for the BR22 secret stage; the stage fails closed without it."""


def _node_bridge(script: str, records: list) -> dict:
    """Send JSON-line records (each with an 'id') to one node process; return id -> result record."""
    node = _program_on_absolute_path("node")
    if not node:
        raise NodeUnavailable()
    payload = "".join(json.dumps(record) + "\n" for record in records)
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script], input=payload.encode("utf-8"), capture_output=True
    )
    if proc.returncode != 0:
        raise ReleaseError(["error=secret_scan_failed"], exit_code=2)
    results = {}
    # D25 model (4): JSON.stringify leaves U+2028/U+2029 raw, so split on newline only.
    for raw in proc.stdout.decode("utf-8").split("\n"):
        raw = raw.removesuffix("\r")
        if raw:
            record = json.loads(raw)
            results[record["id"]] = record
    if set(results) != {record["id"] for record in records}:
        raise ReleaseError(["error=secret_scan_failed"], exit_code=2)
    return results


def scan_texts(items) -> dict:
    """Scan (id, text) items with one node process; return id -> {findings, suppressed}."""
    script = _SCAN_BRIDGE.replace("__PATTERNS__", json.dumps(str(SECRET_PATTERNS_MODULE)))
    return _node_bridge(script, [{"id": item_id, "text": text} for item_id, text in items])


def credential_filenames(paths) -> set:
    """The paths the commit scanner's isCredentialFilename rule matches, checked in one node process.

    The rule sees each path in NFC with trailing dots and spaces stripped from every segment, the
    name Windows extraction writes (SEC-8), so `.npmrc.` is matched; the original path is returned.
    """
    paths = list(paths)
    if not paths:
        return set()
    script = _NAME_BRIDGE.replace("__NAMES__", json.dumps(str(CREDENTIAL_NAMES_MODULE)))
    results = _node_bridge(script, [
        {"id": index, "path": "/".join(seg.rstrip(". ") for seg in unicodedata.normalize("NFC", path).split("/"))}
        for index, path in enumerate(paths)
    ])
    return {path for index, path in enumerate(paths) if results[index]["credential"] is True}


def _is_text(data: bytes) -> bool:
    return b"\0" not in data[:BINARY_PROBE_BYTES]


def _scan_members(data: dict) -> tuple:
    """Masked secret_finding and suppressed_finding lines for text members, plus the binary count."""
    ordered = _utf8_order(data)
    credentials = credential_filenames(ordered)
    texts = [(name, data[name].decode("utf-8", "replace")) for name in ordered if _is_text(data[name])]
    results = scan_texts(texts)
    findings = [
        f"secret_finding={_display_path(name)}:0:{CREDENTIAL_FILENAME_LABEL}" for name in ordered if name in credentials
    ]
    suppressed = []
    for name, _text in texts:
        record = results[name]
        shown = _display_path(name)
        findings += [f"secret_finding={shown}:{f['line']}:{f['label']}" for f in record["findings"]]
        suppressed += [
            f"suppressed_finding={shown}:{s['line']}:{s['label']}:{s['reason']}" for s in record["suppressed"]
        ]
    return findings, suppressed, len(data) - len(texts)


@dataclass
class VerifyReport:
    exit_code: int
    lines: list = field(default_factory=list)


_COMMENT_RE = re.compile(rb"agentic-sdlc-archive source_commit=([0-9a-f]{40}|[0-9a-f]{64})")


def _tree_mode_as_zip_mode(git_mode: str) -> int:
    return 0o100755 if git_mode == "100755" else 0o100644


def _read_archive(raw: bytes, emit) -> tuple | None:
    """Steps 1-2: safe unique member names, then every member readable with a valid CRC."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, NotImplementedError, ValueError, EOFError, OSError):
        emit("error=unreadable_archive")
        return None
    with zf:
        infos = zf.infolist()
        errors, seen = [], set()
        for info in infos:
            name = info.orig_filename
            if name in seen:
                errors.append(f"error=duplicate_member:{_display_path(name)}")
            seen.add(name)
            if exclusion_class(name, info.external_attr >> 16) is not None:
                errors.append(f"error=unsafe_member:{_display_path(name)}")
        errors += _collisions(seen)
        if not errors:
            data = {}
            for info in infos:
                name = info.orig_filename
                # The builder writes only unencrypted STORED members; anything else is named, never raised.
                if info.flag_bits & 0x1:
                    errors.append(f"error=encrypted_member:{name}")
                    continue
                if info.compress_type != zipfile.ZIP_STORED:
                    errors.append(f"error=unsupported_compression:{name}")
                    continue
                try:
                    data[name] = zf.read(info)
                except (zipfile.BadZipFile, zlib.error, EOFError):
                    errors.append(f"error=crc_mismatch:{name}")
                except (NotImplementedError, RuntimeError):
                    errors.append(f"error=unreadable_member:{name}")
        for line in errors:
            emit(line)
        if errors:
            return None
        return data, {info.orig_filename: info.external_attr >> 16 for info in infos}, zf.comment


def verify_archive(zip_path, repo_root) -> VerifyReport:
    """Verify an archive against the recorded commit in repo_root; nothing is written."""
    emit = _Emitter()
    repo_root = Path(repo_root)

    def finish(exit_code: int) -> VerifyReport:
        emit("verify=" + ("passed" if exit_code == 0 else "failed"))
        return VerifyReport(exit_code, emit.lines)

    try:
        raw = Path(zip_path).read_bytes()
    except OSError:
        emit("error=unreadable_archive")
        return finish(2)
    archive_sha = hashlib.sha256(raw).hexdigest()
    read = _read_archive(raw, emit)
    if read is None:
        return finish(1)
    data, modes, comment = read
    recorded = _COMMENT_RE.fullmatch(comment)
    if not recorded:
        emit("error=source_commit_unrecorded")
        return finish(1)
    commit = recorded.group(1).decode("ascii")
    # DP22: without a checkout holding the recorded commit, mode and rebuild checks cannot run.
    # No fetch or clone is attempted, and no partial pass line is printed.
    try:
        if (
            _run_git(["rev-parse", "--show-toplevel"], cwd=repo_root).returncode != 0
            or _run_git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo_root).returncode != 0
        ):
            emit(f"error=source_commit_unavailable:{commit}")
            return finish(1)
        release = _commit_members(commit, cwd=repo_root)
    except ReleaseError as exc:
        for line in exc.lines:
            emit(line)
        return finish(exc.exit_code)
    try:
        skills = _select_skills_only(release)
    except ReleaseError:
        skills = None
    names = set(data)
    kind = "release"
    if names != set(release):
        if skills is not None and (names == set(skills) or len(names ^ set(skills)) < len(names ^ set(release))):
            kind = "skills-only"
    expected = skills if kind == "skills-only" else release
    errors = [f"error=unexpected_member:{n}" for n in _utf8_order(names - set(expected))]
    errors += [f"error=missing_member:{n}" for n in _utf8_order(set(expected) - names)]
    for name in _utf8_order(names & set(expected)):
        git_mode, blob = expected[name]
        if data[name] != blob:
            errors.append(f"error=content_mismatch:{name}")
        if modes[name] != _tree_mode_as_zip_mode(git_mode):
            errors.append(f"error=mode_mismatch:{name}")
    if hashlib.sha256(_zip_bytes(expected, commit)).hexdigest() != archive_sha:
        errors.append(f"error=rebuild_mismatch:{archive_sha}")
    for line in errors:
        emit(line)
    try:
        findings, suppressed, binary_count = _scan_members(data)
    except NodeUnavailable:
        emit("error=node_unavailable")
        return finish(2)
    except ReleaseError as exc:
        for line in exc.lines:
            emit(line)
        return finish(exc.exit_code)
    emit(f"archive_kind={kind}")
    emit(f"source_commit={commit}")
    emit(f"archive_sha256={archive_sha}")
    emit(_identity_line({n: (None, d) for n, d in data.items()}, kind == "skills-only"))
    for line in findings + suppressed:
        emit(line)
    emit(f"suppressed_count={len(suppressed)}")
    emit(f"binary_members_skipped={binary_count}")
    return finish(1 if errors or findings else 0)


SCAN_BATCH_SIZE = 500
MESSAGE_PATH = ":commit-message"
_PULL_HEAD_REF = re.compile(r"^refs/pull/[^/]+/head$")
_LINE_BREAK = re.compile(r"\r?\n")


@dataclass
class HistoryReport:
    exit_code: int
    lines: list = field(default_factory=list)


class _HistoryFindings:
    """Earliest sighting per finding key; keys never contain the matched value (DP23)."""

    def __init__(self):
        self.secrets: dict = {}
        self.suppressed: dict = {}

    @staticmethod
    def _keep_earliest(table: dict, key, entry: dict) -> None:
        current = table.get(key)
        if current is None or entry["order"] < current["order"]:
            table[key] = entry

    def record(self, text: str, result: dict, sightings: list) -> None:
        lines = _LINE_BREAK.split(text)
        for kind, table in (("findings", self.secrets), ("suppressed", self.suppressed)):
            for hit in result[kind]:
                line_sha256 = hashlib.sha256(lines[hit["line"] - 1].strip().encode("utf-8")).hexdigest()
                for commit_index, path in sightings:
                    key = hashlib.sha256(f"{path}\0{hit['label']}\0{line_sha256}".encode("utf-8")).hexdigest()
                    entry = {
                        "order": (commit_index, hit["line"]), "path": path, "label": hit["label"], "key": key,
                        "commit_index": commit_index, "line": hit["line"], "line_sha256": line_sha256,
                        "reason": hit.get("reason"),
                    }
                    self._keep_earliest(table, key if kind == "findings" else (key, hit.get("reason")), entry)

    def record_credential_filename(self, path: str, commit_index: int) -> None:
        """A path-only finding: its DP23 key uses the SHA-256 of the empty trimmed line (SEC-12)."""
        label, line_sha256 = CREDENTIAL_FILENAME_LABEL, hashlib.sha256(b"").hexdigest()
        key = hashlib.sha256(f"{path}\0{label}\0{line_sha256}".encode("utf-8", "surrogateescape")).hexdigest()
        self._keep_earliest(self.secrets, key, {
            "order": (commit_index, 0), "path": path, "label": label, "key": key,
            "commit_index": commit_index, "line": 0, "line_sha256": line_sha256, "reason": None,
        })


def _ordered(table: dict) -> list:
    return sorted(
        table.values(),
        key=lambda e: (e["commit_index"], e["path"].encode("utf-8", "surrogateescape"), e["line"], e["label"]),
    )


# DP23 reviewed findings record. Entries carry keys and states only; a value-bearing or otherwise
# unexpected field invalidates the entry, and an invalid entry never resolves a finding.
_SECRET_ENTRY_FIELDS = ("kind", "path", "label", "line_sha256", "state")
_PRIVATE_ENTRY_FIELDS = ("kind", "path", "class", "state", "accepted_on", "maintainer_reference")
_SECRET_STATES = ("inspected-sample", "false-positive")


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value != ""


def _valid_date(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_https_reference(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.netloc != ""


def _invalid_entry_field(entry) -> str | None:
    """Name of the first missing, extra or invalid field of a record entry, or None when valid."""
    if not isinstance(entry, dict):
        return "entry"
    kind = entry.get("kind")
    if kind == "secret":
        fields = _SECRET_ENTRY_FIELDS
    elif kind == "private-path":
        fields = _PRIVATE_ENTRY_FIELDS
    else:
        return "kind"
    missing = [name for name in fields if name not in entry]
    if missing:
        return missing[0]
    extra = sorted(name for name in entry if name not in fields)
    if extra:
        return extra[0]
    if kind == "secret":
        checks = {
            "path": _nonempty_str(entry["path"]),
            "label": _nonempty_str(entry["label"]),
            "line_sha256": isinstance(entry["line_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", entry["line_sha256"]) is not None,
            "state": isinstance(entry["state"], str) and entry["state"] in _SECRET_STATES,
        }
    else:
        checks = {
            "path": _nonempty_str(entry["path"]),
            "class": type(entry["class"]) is int and 1 <= entry["class"] <= 7,
            "state": entry["state"] == "maintainer-accepted",
            "accepted_on": _valid_date(entry["accepted_on"]),
            "maintainer_reference": _valid_https_reference(entry["maintainer_reference"]),
        }
    return next((name for name in fields[1:] if not checks[name]), None)


def _load_findings_record(record, emit):
    """(secret states by key, accepted private paths, any invalid entry), or None when unreadable."""
    if record is None:
        emit("findings_record=none")
        return {}, set(), False
    path = Path(record)
    if not path.exists():
        emit("findings_record=absent")
        return {}, set(), False
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    emit("findings_record_sha256=" + hashlib.sha256(raw).hexdigest())
    secrets, accepted, invalid = {}, set(), False
    for index, entry in enumerate(data["entries"]):
        field_name = _invalid_entry_field(entry)
        if field_name is not None:
            emit(f"findings_record_entry_invalid={index}:{field_name}")
            invalid = True
        elif entry["kind"] == "secret":
            secrets[(entry["path"], entry["label"], entry["line_sha256"])] = entry["state"]
        else:
            accepted.add((entry["path"], entry["class"]))
    return secrets, accepted, invalid


def scan_history(mirror, record=None) -> HistoryReport:
    """Scan every ref of a local bare mirror for secrets (messages, text blobs) and BR13 private paths.

    record is the DP23 reviewed findings record path, or None for no record.
    """
    emit = _Emitter()
    loaded = _load_findings_record(record, emit)
    if loaded is None:
        emit("error=findings_record_unreadable")
        emit("scan_history=failed")
        return HistoryReport(2, emit.lines)
    recorded_secrets, accepted_paths, record_invalid = loaded
    git = {"git_dir": Path(mirror)}
    findings = _HistoryFindings()
    pending: list = []
    counters = {"batches": 0, "items": 0}

    def flush() -> None:
        if not pending:
            return
        results = scan_texts([(item_id, text) for item_id, text, _sightings in pending])
        counters["batches"] += 1
        for item_id, text, sightings in pending:
            findings.record(text, results[item_id], sightings)
        pending.clear()

    def queue(text: str, sightings: list) -> None:
        pending.append((counters["items"], text, sightings))
        counters["items"] += 1
        if len(pending) >= SCAN_BATCH_SIZE:
            flush()

    try:
        refs = [
            line.split(" ", 2)
            for line in _git_ok(["for-each-ref", "--format=%(objectname) %(objecttype) %(refname)"], **git)
            .decode("utf-8").splitlines()
            if line
        ]
        pull_refs = sum(1 for _oid, _type, name in refs if _PULL_HEAD_REF.match(name))
        commits = _git_ok(["rev-list", "--all", "--topo-order", "--reverse"], **git).decode("ascii").split()
        # Sighting index -> origin: commits first, then every ref whose object is not a commit (AC99).
        origins = list(commits)
        blob_sightings: dict = {}
        private_paths: dict = {}
        tree_paths: dict = {}

        def sight(oid: str, index: int, path: str) -> None:
            sightings = blob_sightings.setdefault(oid, [])
            if all(p != path for _i, p in sightings):
                sightings.append((index, path))

        def sight_tree(treeish: str, index: int) -> None:
            for mode, otype, oid, path in _tree_entries(treeish, **git):
                if otype == "blob":
                    tree_paths.setdefault(path, index)
                # AC125: a BR13 path is reported with its first introducing origin; its content is never read.
                cls = exclusion_class(path, mode)
                if cls is not None:
                    private_paths.setdefault((path, cls), index)
                elif otype == "blob":
                    sight(oid, index, path)

        for index, commit in enumerate(commits):
            sight_tree(commit, index)
        messages = _read_objects(commits, **git)
        for index, commit in enumerate(commits):
            queue(messages[commit].partition(b"\n\n")[2].decode("utf-8", "replace"), [(index, MESSAGE_PATH)])
        # Refs rev-list cannot walk: tag objects (every message in a nested chain), and blob or tree targets.
        peeling = []
        for oid, otype, name in refs:
            if otype != "commit":
                peeling.append([oid, otype, name, len(origins)])
                origins.append(name)
        while any(entry[1] == "tag" for entry in peeling):
            tags = _read_objects([entry[0] for entry in peeling if entry[1] == "tag"], **git)
            for entry in peeling:
                if entry[1] != "tag":
                    continue
                header, _, message = tags[entry[0]].partition(b"\n\n")
                queue(message.decode("utf-8", "replace"), [(entry[3], f":tag-message:{entry[2]}")])
                fields = dict(line.split(b" ", 1) for line in header.split(b"\n") if b" " in line)
                # A header without object/type leaves an empty type, which fails closed below.
                entry[0], entry[1] = (fields.get(b"object", b"").decode("ascii"),
                                      fields.get(b"type", b"").decode("ascii"))
        for oid, otype, name, index in peeling:
            if otype == "tree":
                sight_tree(oid, index)
            elif otype == "blob":
                sight(oid, index, f":ref-blob:{name}")
            elif otype != "commit":
                raise ReleaseError([f"error=unscanned_ref:{name}"])
        oids = list(blob_sightings)
        text_blobs = binary_blobs = 0
        for start in range(0, len(oids), SCAN_BATCH_SIZE):
            chunk = oids[start:start + SCAN_BATCH_SIZE]
            contents = _read_objects(chunk, **git)
            for oid in chunk:
                if _is_text(contents[oid]):
                    text_blobs += 1
                    queue(contents[oid].decode("utf-8", "replace"), blob_sightings[oid])
                else:
                    binary_blobs += 1
        flush()
        for path in credential_filenames(tree_paths):
            findings.record_credential_filename(path, tree_paths[path])
    except NodeUnavailable:
        emit("error=node_unavailable")
        emit("scan_history=failed")
        return HistoryReport(2, emit.lines)
    except ReleaseError as exc:
        for line in exc.lines:
            emit(line)
        emit("scan_history=failed")
        return HistoryReport(exc.exit_code, emit.lines)

    emit(f"refs_scanned={len(refs)}")
    emit(f"pull_refs_scanned={pull_refs}")
    emit(f"commits_scanned={len(commits)}")
    emit(f"text_blobs_scanned={text_blobs}")
    emit(f"binary_blobs_skipped={binary_blobs}")
    emit(f"scan_batches={counters['batches']}")

    def first(index: int) -> str:
        return f"first_commit={origins[index]}" if index < len(commits) else f"first_ref={origins[index]}"

    unresolved = 0
    for entry in _ordered(findings.secrets):
        state = recorded_secrets.get((entry["path"], entry["label"], entry["line_sha256"]), "unresolved")
        unresolved += state == "unresolved"
        emit(
            f"secret_finding=path={_display_path(entry['path'])} label={entry['label']} key={entry['key']} "
            f"{first(entry['commit_index'])} line={entry['line']} state={state}"
        )
    for entry in _ordered(findings.suppressed):
        emit(
            f"suppressed_finding=path={_display_path(entry['path'])} label={entry['label']} "
            f"{first(entry['commit_index'])} line={entry['line']} reason={entry['reason']}"
        )
    for (path, cls), index in sorted(
        private_paths.items(), key=lambda kv: (kv[1], kv[0][0].encode("utf-8", "surrogateescape"), kv[0][1])
    ):
        state = "maintainer-accepted" if (path, cls) in accepted_paths else "unresolved"
        unresolved += state == "unresolved"
        emit(f"private_path_finding=path={_display_path(path)} class={cls} {first(index)} state={state}")
    emit(f"unresolved_count={unresolved}")
    passed = unresolved == 0 and not record_invalid
    emit("scan_history=" + ("passed" if passed else "failed"))
    return HistoryReport(0 if passed else 1, emit.lines)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# D14: the CLI reads the reviewed record from this fixed, gitignored path under the script's own
# repository root (never Path.cwd()); the spec interface admits no record option.
FINDINGS_RECORD_PATH = REPOSITORY_ROOT / "tests" / "artifacts" / "publication" / "history" / "reviewed-findings.json"
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_URL_SCP = re.compile(r"^[^/\\\s]+@[^/\\\s:]+:")
# User-info runs to the LAST '@' before the first '/', so an unescaped '@' inside a credential never leaks.
_URL_USER_INFO = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/]*@")
_SCP_USER_INFO = re.compile(r"^([^/]*)@")


def _masked_url(argument: str) -> str:
    """AC126: replace URL user-info with ***MASKED***; the bare scp user 'git' carries no credential."""
    if _URL_SCHEME.match(argument):
        return _URL_USER_INFO.sub(r"\1***MASKED***@", argument)
    user = _SCP_USER_INFO.match(argument)
    if user and user.group(1) != "git":
        return "***MASKED***" + argument[user.end(1):]
    return argument


def _history_mirror(argument: str, emit) -> Path | None:
    """AC126/AC101 guards for --scan-history; returns the bare mirror path or None after a named error."""
    # (1) A URL is rejected before any git process starts, with credential-bearing user-info masked.
    if _URL_SCHEME.match(argument) or _URL_SCP.match(argument):
        emit("error=url_argument_rejected:" + _masked_url(argument))
        return None
    # (2) Pure-path containment check before any existence check, so nothing is created.
    mirror = Path(argument).resolve()
    roots = [REPOSITORY_ROOT]
    try:
        toplevel = _run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
    except ReleaseError as exc:
        for line in exc.lines:
            emit(line)
        return None
    if toplevel.returncode == 0 and toplevel.stdout.strip():
        roots.append(Path(toplevel.stdout.decode("utf-8").strip()).resolve())
    if any(mirror == root or mirror.is_relative_to(root) for root in roots):
        emit("error=mirror_inside_repository")
        return None
    # (3) and (4): an existing bare repository only.
    if not mirror.is_dir():
        emit("error=mirror_missing")
        return None
    bare = _run_git(["rev-parse", "--is-bare-repository"], git_dir=mirror)
    if bare.returncode != 0 or bare.stdout.strip() != b"true":
        emit("error=mirror_not_bare")
        return None
    return mirror


# D4 verbose-log grammar. The result-line pattern tolerates the docstring line Python 3.11+ prints
# between the test id and the outcome; failure ids also come from the summary headers, so a result
# the pattern cannot see is never counted as a pass (fail closed).
# Limit (QUAL-17): a result line that test stderr output splits is not matched. A skipped result split
# that way is missing from the parsed skips, so the parsed skip count differs from the summary's
# skipped=N and the comparison fails closed: a possible false failure, never a false pass.
_RESULT_LINE = re.compile(
    r"^\S+ \(([\w.]+)\)(?:\n[^\n]*?)? \.\.\. (ok|skipped '.*'|FAIL|ERROR|expected failure|unexpected success)$",
    re.M,
)
_FAILURE_HEADER = re.compile(r"^(?:FAIL|ERROR): \S+ \(([\w.]+)\)", re.M)
_RAN_LINE = re.compile(r"^Ran (\d+) tests?\b", re.M)
_SUMMARY_LINE = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?$", re.M)


def check_archive_gate_log(log_path, source_root) -> int:
    """AC102: the extracted-archive unit-test log runs as many tests as the source tree, all named skips."""
    emit = _Emitter()
    errors = []
    # D17: count source tests exactly the way the gate runs them (tests/ is not a package).
    source = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=source_root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    source_counts = _RAN_LINE.findall((source.stdout or "") + "\n" + (source.stderr or ""))
    # A failed discovery still prints 'Ran 0 tests'; a zero count is never a usable baseline.
    if not source_counts or int(source_counts[-1]) == 0:
        emit("error=source_count_unavailable")
        emit("archive_coverage=failed")
        return 1
    source_tests = int(source_counts[-1])
    emit(f"source_tests={source_tests}")
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        emit("error=archive_log_unreadable")
        emit("archive_coverage=failed")
        return 1
    archive_counts = _RAN_LINE.findall(text)
    summaries = _SUMMARY_LINE.findall(text)
    if not archive_counts or not summaries:
        errors.append("error=archive_log_incomplete")
    archive_tests = int(archive_counts[-1]) if archive_counts else 0
    outcome, detail = summaries[-1] if summaries else ("FAILED", "")
    summary = {k.strip(): int(v) for k, v in re.findall(r"(\w+)=(\d+)", detail or "")}
    emit(f"archive_tests_run={archive_tests}")
    emit(f"archive_skipped={summary.get('skipped', 0)}")
    results = list(_RESULT_LINE.finditer(text))
    skips = []
    for match in results:
        if match.group(2).startswith("skipped "):
            try:
                reason = ast.literal_eval(match.group(2)[len("skipped "):])
            except (ValueError, SyntaxError):
                reason = ""
            skips.append((match.group(1), str(reason)))
    for test_id, reason in skips:
        emit(f"skip_reason={test_id}:{reason}")
    failing = {m.group(1) for m in _FAILURE_HEADER.finditer(text)}
    failing |= {m.group(1) for m in results if m.group(2) in ("FAIL", "ERROR", "unexpected success")}
    if outcome != "OK" or failing or summary.get("failures", 0) or summary.get("errors", 0):
        errors.append(f"error=archive_tests_failed:{len(failing)}")
    if len(skips) != summary.get("skipped", 0):
        errors.append(f"error=skip_count_mismatch:parsed={len(skips)}:summary={summary.get('skipped', 0)}")
    errors += [f"error=empty_skip_reason:{test_id}" for test_id, reason in skips if not reason.strip()]
    if archive_tests != source_tests:
        errors.append(f"error=test_count_mismatch:source={source_tests}:archive={archive_tests}")
    for line in errors:
        emit(line)
    emit("archive_coverage=" + ("failed" if errors else "passed"))
    return 1 if errors else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", metavar="ZIP", help="build an archive from the recorded HEAD commit")
    mode.add_argument("--verify", metavar="ZIP", help="verify an archive against its recorded commit")
    mode.add_argument("--scan-history", metavar="MIRROR", help="scan a local bare mirror")
    parser.add_argument(
        "--skills-only", action="store_true", help="with --output: build the BR24 skills-only archive"
    )
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.skills_only and not args.output:
        parser.error("--skills-only is accepted only together with --output")
    if args.output:
        return build_archive(Path.cwd(), Path(args.output), skills_only=args.skills_only).exit_code
    if args.verify:
        return verify_archive(Path(args.verify), Path.cwd()).exit_code
    mirror = _history_mirror(args.scan_history, _Emitter())
    if mirror is None:
        return 2
    return scan_history(mirror, record=FINDINGS_RECORD_PATH).exit_code


if __name__ == "__main__":
    sys.exit(main())

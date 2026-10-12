"""Stage history-free source and vendor review packets without publishing.

Use an exact committed source; intentional catalog/README projections are recorded
separately from the source and from the currently executing producer code. Official
vendor tools run later in copied validation fixtures, outside these checked trees.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

try:
    from scripts import build_release
    from scripts.check_plugin_portability import MANIFESTS, portability_errors
except ModuleNotFoundError:
    import build_release
    from check_plugin_portability import MANIFESTS, portability_errors


PRODUCER_ROOT = Path(__file__).resolve().parents[1]
PRODUCERS = (
    "scripts/prepare_marketplace_release.py", "scripts/build_release.py",
    "scripts/check_plugin_portability.py", "scripts/eval_safety.py",
    "hooks/secret-patterns.mjs", "hooks/scan-commit-names.mjs",
)
PREFIXES = {"clean-source": "clean-source", "grok": "grok-catalog/external_plugins/agentic-sdlc",
            "zcode": "zcode-catalog/plugins/agentic-sdlc"}
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\Z")


@dataclass
class PreparationResult:
    exit_code: int
    lines: list[str]


class PreparationError(Exception):
    def __init__(self, lines, exit_code=1):
        self.lines, self.exit_code = lines, exit_code


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _git_metadata(path):
    return any(part.casefold().rstrip(". ") == ".git"
               or re.fullmatch(r"\.?git~[1-9]\d*", part, re.IGNORECASE)
               for part in path.split("/"))


def _validate_members(members):
    errors = []
    for path, (mode, blob) in members.items():
        if (mode not in ("100644", "100755") or _git_metadata(path)
                or build_release.exclusion_class(path, mode) is not None):
            errors.append("error=unsafe_member:" + build_release._display_path(path))
        elif not isinstance(blob, bytes):
            errors.append("error=invalid_member:" + path)
    errors += build_release._collisions(members)
    if errors:
        raise PreparationError(sorted(errors))


def _manifest(source, path):
    try:
        manifest = json.loads(source[path][1])
    except (KeyError, ValueError, UnicodeDecodeError):
        raise PreparationError(["error=manifest_invalid:" + path]) from None
    if (not isinstance(manifest, dict) or manifest.get("name") != "agentic-sdlc"
            or not isinstance(manifest.get("description"), str) or not manifest["description"].strip()
            or not isinstance(manifest.get("author"), dict)
            or not isinstance(manifest["author"].get("name"), str)
            or not manifest["author"]["name"].strip()
            or (path == ".grok-plugin/plugin.json" and
                (not isinstance(manifest.get("homepage"), str) or not manifest["homepage"].strip()))):
        raise PreparationError(["error=manifest_invalid:" + path])
    return manifest


def _validate_source(source):
    _validate_members(source)
    required = set(MANIFESTS) | set(build_release.PUBLIC_RUNTIME_HELPERS) | {
        "LICENSE", "VERSION", "README.md", "docs/data-handling.md",
        "skills/using-agentic-sdlc/SKILL.md", "skills/agentic-sdlc-pipeline/SKILL.md",
        "skills/agentic-sdlc-pipeline/templates.md", "skills/agentic-sdlc-pipeline/playbook.md",
    }
    required |= {"agents/" + name + ".md" for name in build_release.PUBLIC_ROLES}
    required |= {"docs/" + name + ".md" for name in build_release.PUBLIC_DOCS}
    missing = sorted(path for path in required if path not in source or not source[path][1].strip())
    if missing:
        raise PreparationError(["error=missing_companion:" + path for path in missing])
    try:
        version = source["VERSION"][1].decode("utf-8").strip()
    except UnicodeDecodeError:
        version = ""
    if not VERSION.fullmatch(version):
        raise PreparationError(["error=invalid_release_version"])
    manifests = {path: _manifest(source, path) for path in MANIFESTS}
    for path, manifest in manifests.items():
        if manifest.get("version") != version:
            raise PreparationError(["error=version_mismatch:" + path])
    interface = manifests[".codex-plugin/plugin.json"].get("interface")
    if not isinstance(interface, dict):
        raise PreparationError(["error=manifest_invalid:.codex-plugin/plugin.json"])
    for field in ("composerIcon", "logo"):
        path = interface.get(field)
        if not isinstance(path, str) or build_release._is_unsafe_path(path.removeprefix("./")):
            raise PreparationError(["error=invalid_asset_reference"])
        path = path.removeprefix("./")
        if path not in source or not source[path][1]:
            raise PreparationError(["error=missing_companion:" + path])
    errors = portability_errors({path: blob for path, (_mode, blob) in source.items()})
    if errors:
        raise PreparationError(["error=" + error for error in errors])
    return version, manifests


def _zcode_readme(version, chinese=False):
    # Equivalent review-packet instructions; the original shared runtime stays byte-identical.
    if chinese:
        text = f"""# Agentic SDLC：ZCode 适配器

版本 {version} · MIT。此包提供共享的 SDLC 技能、命令、代理角色和有限的 Hook。
这是实验性适配器。供应商校验成功不代表已发布，也不代表已验证客户端执行、信任或模型行为。

## 依赖和安装

需要 ZCode、同一操作系统环境中的 Node.js，以及 Hook shell PATH 上的 node。
辅助流程需要 Python 3（已在 3.12 上测试；技能运行的辅助脚本经静态检查保持与 3.8 的导入兼容）和 Git。使用宿主正常的模型提供商与身份验证；
插件不需要额外的 API 服务、凭据或 MCP 服务器。保留完整插件，包括 skills、agents、commands、hooks、scripts、contracts 和 docs。
在 ZCode 的 Settings → Plugins → Discover 中添加提供此包的 marketplace，选择 agentic-sdlc，
然后 Install 并开启新会话。ZCode 默认启用新安装的插件。官方市场接受和发布是单独的维护者操作。

## 使用、更新和卸载

使用 $using-agentic-sdlc（或 Skills 菜单）选择最小充分的流程。完整 SDLC 使用
agentic-sdlc-pipeline；git-safety-check 是手动只读评审命令。
刷新 marketplace，在 Manage installed 中选择 Check for updates，应用更新并开启新会话。
在原生插件详情中卸载。持久数据保留规则未验证；不要手动删除宿主配置、目录或共享数据。

## 副作用与安全边界

插件安装后默认启用，其确定性 Hook 随即可以执行本地 Node.js 和 Git 命令，并读取 Hook stdin 与项目状态。
PreToolUse 对 Bash 使用 scan-commit、destructive-command-guard 和 branch-guard。
PostToolUse 对 Write|Edit 使用 scan-write；SessionStart 使用 session-start。
这些 Hook 不调用网络；未声明 MCP 服务器。技能执行可使用宿主的模型和网络工具，并在获得授权后
编辑项目或生成 SDLC 工件。Git 写操作需要用户明确授权。不会修改用户的信任或权限。
长期插件数据应使用 ZCODE_PLUGIN_DATA，不应写入安装目录。

## 能力限制

Stop/flow transcript 读取器未接线；不能把 Claude/Codex 的读取器当作 ZCode 原生证据。
建议写入信息使用 additionalContext，原生交付仍需验证。无可分发的 Claude JavaScript Workflow
运行时；使用可用的原生代理执行作者 → 评审 → 修订，否则明确记录降级流程。
从已安装 Skill 的路径定位辅助脚本，不要依赖开发者的目录。
参见 [运行时边界](docs/runtime-adapter.md) 与 [发行说明](docs/publication/multi-platform-distribution.md)。

## 许可证和来源

Agentic SDLC 使用 [MIT 许可证](LICENSE)。流程设计受到 [obra/superpowers](https://github.com/obra/superpowers)
（MIT）的 RED/GREEN/REFACTOR、调试和验证实践影响。未添加第三方预编译程序、额外遥测或远程安装器。
"""
    else:
        text = f"""# Agentic SDLC: ZCode adapter

Version {version} · MIT. This package provides shared SDLC skills, commands, agent roles and limited hooks.
This is an experimental adapter. Vendor validation establishes neither publication nor verified client execution,
trust or model behavior.

## Prerequisites and installation

Use ZCode and Node.js in the same OS environment, with node on the hook shell PATH.
Helper workflows require Python 3 (3.12 tested; the helpers skills run are kept import-compatible with 3.8 by a static check) and Git.
Use the host's ordinary model provider and authentication; the plugin needs no additional API service,
credentials or MCP server. Keep the full plugin, including skills, agents, commands, hooks, scripts,
contracts and docs.
In ZCode Settings → Plugins → Discover, add the marketplace supplying this package, select agentic-sdlc,
then Install and start a new session. ZCode enables newly installed plugins by default.
Official acceptance and publication are separate maintainer actions.

## Use, update and uninstall

Use $using-agentic-sdlc (or the Skills menu) to select the smallest sufficient procedure.
Use agentic-sdlc-pipeline for the full SDLC; git-safety-check is a manual read-only review command.
Refresh the marketplace, select Check for updates in Manage installed, apply and start a new session.
Uninstall through native plugin details. Persistent-data retention is unverified; do not manually remove
host configuration, catalogs or shared data.

## Side effects and security boundaries

The plugin is enabled by default once installed, which permits deterministic hooks to execute local Node.js/Git commands
and read hook stdin/project state.
PreToolUse on Bash runs scan-commit, destructive-command-guard and branch-guard.
PostToolUse on Write|Edit runs scan-write; SessionStart runs session-start.
These hooks make no network calls; no MCP server is declared. Skills may use the host's model/web tools and
edit approved project files or generate SDLC artifacts. Git writes require explicit user authorization.
The plugin does not change user trust or permissions. Durable plugin data belongs under ZCODE_PLUGIN_DATA,
outside the installed directory.

## Capability limits

Stop/flow transcript readers are unwired; Claude/Codex readers are not ZCode-native evidence.
Write advice uses additionalContext; native delivery still needs verification. There is no distributable
Claude JavaScript Workflow runtime; use available native agents for author → critic → revise, or report degradation.
Locate helper scripts from the installed Skill path, without developer-specific directories.
See [runtime boundaries](docs/runtime-adapter.md) and [distribution guidance](docs/publication/multi-platform-distribution.md).

## License and provenance

Agentic SDLC uses the [MIT license](LICENSE). [obra/superpowers](https://github.com/obra/superpowers) (MIT)
influenced RED/GREEN/REFACTOR, debugging and verification procedures. No third-party prebuilt binaries,
additional telemetry or remote installer are added.
"""
    return text.encode("utf-8")


def _project(source, version, manifests):
    projected = {prefix + "/" + path: item
                 for prefix in PREFIXES.values() for path, item in source.items()}
    grok = manifests[".grok-plugin/plugin.json"]
    catalog = {"name": "agentic-sdlc-review", "description": "Local vendor-review fixture; not published.",
               "owner": grok["author"], "plugins": [{
                   "name": "agentic-sdlc", "description": grok["description"], "version": version,
                   "source": {"type": "local", "path": "./external_plugins/agentic-sdlc"},
                   "homepage": grok["homepage"], "category": "development",
                   "keywords": ["agentic-sdlc", "agentic sdlc"]}]}
    projected["grok-catalog/.grok-plugin/marketplace.json"] = ("100644", _json_bytes(catalog))
    zcode = manifests[".zcode-plugin/plugin.json"]
    localized = zcode.get("description_i18n")
    if not isinstance(localized, dict) or any(not isinstance(localized.get(k), str)
                                             or not localized[k].strip() for k in ("en", "zh-CN")):
        raise PreparationError(["error=localized_metadata_missing"])
    catalog = {"name": "agentic-sdlc-review", "description": "Local vendor-review fixture; not published.",
               "description_i18n": {"en": "Local vendor-review fixture; not published.",
                                    "zh-CN": "本地供应商评审工件；尚未发布。"},
               "owner": zcode["author"], "plugins": [{
                   "name": "agentic-sdlc", "version": version, "source": "./plugins/agentic-sdlc",
                   "description": zcode["description"], "description_i18n": localized,
                   "category": "developer-tools", "author": zcode["author"]}]}
    projected["zcode-catalog/marketplace.json"] = ("100644", _json_bytes(catalog))
    root = PREFIXES["zcode"]
    if "README_CN.md" in source:
        raise PreparationError(["error=projection_collision:README_CN.md"])
    projected[root + "/README.md"] = ("100644", _zcode_readme(version))
    projected[root + "/README_CN.md"] = ("100644", _zcode_readme(version, True))
    _validate_members(projected)
    return projected


def _producer():
    return {path: hashlib.sha256((PRODUCER_ROOT / path).read_bytes()).hexdigest()
            for path in PRODUCERS}


def _receipt(source, projected, commit):
    def inventory(members):
        return {path: {"sha256": hashlib.sha256(blob).hexdigest(), "git_mode": mode}
                for path, (mode, blob) in sorted(members.items())}
    return {"schema_version": 1, "source_commit": commit, "source": inventory(source),
            "outputs": inventory(projected), "producer": _producer(),
            "publication_status": "not-published", "vendor_validation": "not-run",
            "native_validation": "not-run", "original_history": "not-exported"}


def _read_source(repo, commit):
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise PreparationError(["error=invalid_source_commit"], 2)
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise PreparationError(["error=source_repository_unavailable"], 2)
    top = build_release._run_git(["rev-parse", "--show-toplevel"], cwd=repo)
    if top.returncode:
        raise PreparationError(["error=source_repository_unavailable"], 2)
    if Path(top.stdout.decode("utf-8").strip()).resolve() != repo:
        raise PreparationError(["error=source_root_not_repository_root"], 2)
    exists = build_release._run_git(["cat-file", "-e", commit + "^{commit}"], cwd=repo)
    if exists.returncode:
        raise PreparationError(["error=source_commit_unavailable"], 2)
    source = build_release._commit_members(commit, cwd=repo)
    version, manifests = _validate_source(source)
    return repo, source, _project(source, version, manifests)


def _destination(repo, output, source, *, existing=False):
    raw = Path(os.path.abspath(output))
    if any(parent.is_symlink() or parent.is_junction() for parent in (raw, *raw.parents)):
        raise PreparationError(["error=output_symlink_alias"])
    target = raw.resolve()
    if target == repo or target in repo.parents:
        raise PreparationError(["error=output_source_overlap"])
    if target.is_relative_to(repo):
        rel = target.relative_to(repo)
        namespace = rel.parts[0] if rel.parts else ""
        if (namespace not in ("build", "dist")
                or namespace in {path.split("/")[0] for path in source}
                or build_release._run_git(["check-ignore", "--quiet", "--no-index", "--", rel.as_posix()],
                                          cwd=repo).returncode != 0):
            raise PreparationError(["error=output_source_overlap"])
    if not existing and target.exists():
        raise PreparationError(["error=output_exists"])
    if existing and not target.is_dir():
        raise PreparationError(["error=output_unavailable"])
    return target


def _scan(source, projected):
    # Exact source copies inherit the source scan; independently scan novel projected
    # bytes and every output credential filename instead of rescanning three copies.
    source_bytes = {path: blob for path, (_mode, blob) in source.items()}
    source_digests = {hashlib.sha256(blob).digest() for blob in source_bytes.values()}
    novel = {path: blob for path, (_mode, blob) in projected.items()
             if hashlib.sha256(blob).digest() not in source_digests}
    findings = build_release._scan_members(source_bytes)[0] + build_release._scan_members(novel)[0]
    findings += ["secret_finding=" + path + ":0:credential-filename"
                 for path in sorted(build_release.credential_filenames(projected))]
    if findings:
        raise PreparationError(["error=" + line for line in findings])


def _write_tree(output, members):
    created_dirs, created_files = [], []
    try:
        def mkdir(path):
            if not path.exists():
                mkdir(path.parent)
                path.mkdir()
                created_dirs.append(path)

        # Exclusive root admission precedes all file writes; existing targets are untouched.
        mkdir(output.parent)
        output.mkdir()
        created_dirs.append(output)
        for rel, (mode, blob) in sorted(members.items()):
            path = output / rel
            mkdir(path.parent)
            with path.open("xb") as handle:
                created_files.append(path)
                handle.write(blob)
            if os.name != "nt" and mode == "100755":
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        # Delete only files/directories created by this invocation, never recursively
        # remove a preexisting directory or a concurrently added sibling.
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass
        for path in reversed(created_dirs):
            try:
                path.rmdir()
            except OSError:
                pass
        raise PreparationError(["error=output_write_failed"], 2) from None


def _result(action, error=None, **facts):
    lines = error.lines if error else [key + "=" + str(value) for key, value in facts.items()]
    lines = [*lines, action + "=" + ("failed" if error else "passed")]
    for line in lines:
        print(line)
    return PreparationResult(error.exit_code if error else 0, lines)


def prepare(repo_root, source_commit, output_root):
    try:
        repo, source, projected = _read_source(repo_root, source_commit)
        output = _destination(repo, output_root, source)
        _scan(source, projected)
        receipt = _receipt(source, projected, source_commit)
        members = dict(projected, **{"receipt.json": ("100644", _json_bytes(receipt))})
        _write_tree(output, members)
    except (PreparationError, build_release.ReleaseError) as error:
        return _result("prepare", error)
    except build_release.NodeUnavailable:
        return _result("prepare", PreparationError(["error=node_unavailable"], 2))
    except (OSError, RuntimeError):
        return _result("prepare", PreparationError(["error=preparation_environment_error"], 2))
    return _result("prepare", source_commit=source_commit, source_members=len(source),
                   projected_members=len(projected), publication_status="not-published")


def verify_preparation(repo_root, source_commit, output_root):
    try:
        repo, source, projected = _read_source(repo_root, source_commit)
        output = _destination(repo, output_root, source, existing=True)
        _scan(source, projected)
        expected_receipt = _receipt(source, projected, source_commit)
        try:
            if (output / "receipt.json").is_symlink():
                raise PreparationError(["error=unsafe_output_member:receipt.json"])
            receipt = json.loads((output / "receipt.json").read_bytes())
        except (OSError, ValueError):
            raise PreparationError(["error=receipt_invalid"]) from None
        if not isinstance(receipt, dict):
            raise PreparationError(["error=receipt_invalid"])
        if receipt.get("producer") != expected_receipt["producer"]:
            raise PreparationError(["error=producer_identity_mismatch"])
        if receipt != expected_receipt:
            raise PreparationError(["error=receipt_mismatch"])
        expected = dict(projected, **{"receipt.json": ("100644", _json_bytes(expected_receipt))})
        found, errors = set(), []
        for directory, dirs, files in os.walk(output, followlinks=False):
            for name in (*dirs, *files):
                path = Path(directory) / name
                if path.is_symlink() or path.is_junction():
                    errors.append("error=unsafe_output_member:" +
                                  build_release._display_path(path.relative_to(output).as_posix()))
            # NTFS junctions are directories rather than symbolic links. Prune
            # every alias before os.walk can enumerate bytes outside the packet.
            dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()
                       and not (Path(directory) / name).is_junction()]
            for name in files:
                found.add((Path(directory) / name).relative_to(output).as_posix())
        errors += ["error=missing_output_member:" + path for path in sorted(set(expected) - found)]
        errors += ["error=unexpected_output_member:" + build_release._display_path(path)
                   for path in sorted(found - set(expected))]
        if errors:
            raise PreparationError(errors)
        for path, (_mode, blob) in expected.items():
            target = output / path
            if target.stat().st_size != len(blob) or target.read_bytes() != blob:
                errors.append("error=output_content_mismatch:" + path)
        if errors:
            raise PreparationError(errors)
    except (PreparationError, build_release.ReleaseError) as error:
        return _result("verify_preparation", error)
    except build_release.NodeUnavailable:
        return _result("verify_preparation", PreparationError(["error=node_unavailable"], 2))
    except (OSError, RuntimeError):
        return _result("verify_preparation", PreparationError(["error=verification_environment_error"], 2))
    return _result("verify_preparation", source_commit=source_commit, output_members=len(expected),
                   publication_status="not-published")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PRODUCER_ROOT)
    parser.add_argument("--source-commit", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    operation = verify_preparation if args.verify is not None else prepare
    return operation(args.source_root, args.source_commit, args.verify or args.output).exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""Start-time probes: workspace shape, dependencies, build toolchain and git facts.

The three detectors are the functions of scripts/detect_context.py (`detect`, `probe_deps`,
`probe_toolchain`), loaded by file path from the runner's own plugin root, never through
sys.path, the cwd or the user's project, where a planted detect_context.py would run instead.
A detector that raises or returns a malformed result is recorded as "error" with a named entry in
`errors`; the design reads a probe error as "the step applies", so a broken detector can only add
work, never skip a step.
"""
from __future__ import annotations

import importlib.util
import json

from . import gitinfo, mask, paths

ERROR = "error"
# (result key, detect_context function, field holding the value)
PROBES = (
    ("explore_mode", "detect", "explore_mode"),
    ("deps", "probe_deps", "deps_probe"),
    ("toolchain", "probe_toolchain", "toolchain_probe"),
)
_ERROR_CHARS = 300
_DETECTOR = []


def detector():
    """scripts/detect_context.py of this plugin, loaded once by path."""
    if not _DETECTOR:
        source = paths.plugin_root() / "scripts" / "detect_context.py"
        spec = importlib.util.spec_from_file_location("_sdlc_detect_context", str(source))
        if spec is None or spec.loader is None:
            raise ImportError("cannot load " + str(source))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _DETECTOR.append(module)
    return _DETECTOR[0]


def _reset_cache() -> None:
    """Forget the loaded detector (tests)."""
    del _DETECTOR[:]


def _describe(probe: str, exc: BaseException) -> str:
    """One masked line: `<probe>: <error class>: <message>`, at most 300 characters."""
    text = "%s: %s: %s" % (probe, type(exc).__name__, exc)
    return " ".join(mask.mask_text(text).split())[:_ERROR_CHARS]


def start_probes(project) -> dict:
    """{"explore_mode", "deps", "toolchain", "errors", "details", "git"}; never raises.

    `explore_mode` is parallel|single|greenfield_inline, `deps` external|stdlib_only, `toolchain`
    present|absent, each "error" when its detector failed. `details` holds each successful
    detector's full result (layers, manifests, toolchains); `git` is gitinfo.facts(project).
    """
    result = {"explore_mode": ERROR, "deps": ERROR, "toolchain": ERROR, "errors": [], "details": {}}
    try:
        module, load_error = detector(), None
    except Exception as exc:  # a missing or broken detector file
        module, load_error = None, exc
    for key, function, field in PROBES:
        if module is None:
            result["errors"].append(_describe(key, load_error))
            continue
        try:
            raw = getattr(module, function)([str(project)])
            value = raw[field]
            if not isinstance(value, str) or not value:
                raise ValueError("%s is %r, not a non-empty string" % (field, value))
            details = json.loads(json.dumps(raw))  # what lands in state.json must be JSON
        except Exception as exc:
            result["errors"].append(_describe(key, exc))
            continue
        result[key] = value
        result["details"][key] = details
    try:
        result["git"] = gitinfo.facts(project)
    except Exception as exc:  # facts() never raises; this keeps start_probes' promise if it did
        result["git"] = None
        result["errors"].append(_describe("git", exc))
    return result

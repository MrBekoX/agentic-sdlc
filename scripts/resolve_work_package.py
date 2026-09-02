"""Resolve the active AGENTIC-SDLC spec/plan work package.

This is an identity resolver, not a content validator. `validate_artifacts.py`
still checks the markdown body. This script answers which spec/plan pair
`implementation-control` should audit and refuses ambiguous choices.

Output is sorted `key=value` lines. Exit 1 on failed resolution.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path


SPEC_ROOT = Path("docs") / "agentic-sdlc" / "specs"
PLAN_ROOT = Path("docs") / "agentic-sdlc" / "plans"
AGENTIC_ROOT = Path("docs") / "agentic-sdlc"
STATUSES = {"draft", "reviewed", "in_progress", "ready_for_audit", "complete"}
PLAN_REQUIRED = ("work_id", "spec", "branch", "status")
SPEC_REQUIRED = ("work_id", "status")

# Per-package layout (BR1/BR2/BR11): docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md.
# The slug rule is shared; tests/test_procedure_eval.py pins it in lock-step with the
# flow-guard config (hooks/flow-requirements.json) and run_procedure_eval.py.
RESERVED_SLUGS = {"specs", "plans", "evidence", "notes", "spec", "plan"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
PER_PACKAGE_ROLES = {"spec", "plan", "evidence"}


class Resolution:
    def __init__(
        self,
        ok=False,
        source=None,
        work_id=None,
        spec=None,
        plan=None,
        branch=None,
        status=None,
        errors=None,
        candidates=None,
        layout=None,
        slug=None,
    ):
        self.ok = ok
        self.source = source
        self.work_id = work_id
        self.spec = spec
        self.plan = plan
        self.branch = branch
        self.status = status
        self.errors = errors or []
        self.candidates = candidates or []
        self.layout = layout
        self.slug = slug


def _as_repo_path(repo, path):
    p = Path(path)
    if not p.is_absolute():
        p = repo / p
    return p.resolve(strict=False)


def _is_inside(path, root):
    path = path.resolve(strict=False)
    root = root.resolve(strict=False)
    return path == root or root in path.parents


def _rel(repo, path):
    try:
        return path.resolve(strict=False).relative_to(repo.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def is_valid_slug(seg):
    """A <slug> segment is filesystem-safe kebab-case and not a reserved name (BR2/BR11)."""
    return bool(SLUG_RE.match(seg)) and seg not in RESERVED_SLUGS


def classify_artifact(repo, path):
    """Classify an artifact path: flat | per-package | None.

    Returns {"layout", "slug", "role", "basename"}. slug/role/basename are read from
    the resolved path components (a trusted normalized path), never assembled from
    frontmatter text (spec §6 sink discipline). layout is None for anything not under a
    recognized root or under an invalid/reserved slug.
    """
    repo = Path(repo).resolve(strict=False)
    p = _as_repo_path(repo, path)
    result = {"layout": None, "slug": None, "role": None, "basename": p.stem}
    try:
        rel = p.relative_to((repo / AGENTIC_ROOT).resolve(strict=False))
    except ValueError:
        return result
    parts = rel.parts
    # flat: specs/<id>.md or plans/<id>.md
    if len(parts) == 2 and parts[0] in ("specs", "plans") and parts[1].endswith(".md"):
        result["layout"] = "flat"
        result["role"] = "spec" if parts[0] == "specs" else "plan"
        return result
    # per-package: <slug>/<role>/<basename>.md
    if len(parts) == 3 and parts[2].endswith(".md"):
        slug, role = parts[0], parts[1]
        if is_valid_slug(slug) and role in PER_PACKAGE_ROLES:
            result["layout"] = "per-package"
            result["slug"] = slug
            result["role"] = role
    return result


def recognized_root(repo, path, role):
    """True if path (after symlink resolution) is inside a recognized root for role.

    A recognized root is the flat root (`docs/agentic-sdlc/specs|plans`) **or** any
    per-package `docs/agentic-sdlc/<valid-slug>/<role>/` (BR9). This replaces the
    single-root `_is_inside(..., SPEC_ROOT|PLAN_ROOT)` gate while preserving its
    symlink-resolving traversal guard via `_is_inside`/`resolve(strict=False)`.
    """
    repo = Path(repo).resolve(strict=False)
    p = _as_repo_path(repo, path)
    flat_root = repo / (SPEC_ROOT if role == "spec" else PLAN_ROOT)
    if _is_inside(p, flat_root):
        return True
    try:
        rel = p.relative_to((repo / AGENTIC_ROOT).resolve(strict=False))
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 2 and is_valid_slug(parts[0]) and parts[1] == role


def _bad_slug_path(repo, path, role):
    """True if path has per-package <seg>/<role>/<file>.md shape but <seg> is an
    invalid/reserved slug (AC14). Distinguishes a directed audit at a malformed slug
    (→ bad_slug) from a path that is simply outside every root (→ *_outside_root)."""
    repo = Path(repo).resolve(strict=False)
    p = _as_repo_path(repo, path)
    try:
        rel = p.relative_to((repo / AGENTIC_ROOT).resolve(strict=False))
    except ValueError:
        return False
    parts = rel.parts
    return (
        len(parts) == 3
        and parts[1] == role
        and parts[2].endswith(".md")
        and not is_valid_slug(parts[0])
    )


def _malformed_offenders(repo, slug):
    """Offending files if a per-package <slug>/spec or <slug>/plan holds >1 distinct
    basename (AC20/BR2) — a 1:1 slug↔package violation that must never be auto-resolved."""
    repo = Path(repo).resolve(strict=False)
    for role in ("spec", "plan"):
        role_dir = repo / AGENTIC_ROOT / slug / role
        if not role_dir.exists():
            continue
        files = sorted(role_dir.glob("*.md"))
        if len({f.stem for f in files}) > 1:
            return files
    return []


def _parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, ["missing_frontmatter"]
    end = text.find("\n---", 3)
    if end == -1:
        return {}, ["missing_frontmatter_end"]
    block = text[3:end]
    data = {}
    errors = []
    for lineno, raw in enumerate(block.splitlines(), start=2):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            errors.append(f"invalid_frontmatter_line:{lineno}")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key:
            errors.append(f"invalid_frontmatter_line:{lineno}")
            continue
        data[key] = value
    return data, errors


def _validate_spec(repo, spec_path):
    spec_path = _as_repo_path(repo, spec_path)
    errors = []
    if _bad_slug_path(repo, spec_path, "spec"):
        errors.append("bad_slug")
        return None, errors
    if not recognized_root(repo, spec_path, "spec"):
        errors.append("spec_outside_root")
        return None, errors
    if not spec_path.exists():
        errors.append("spec_not_found")
        return None, errors
    meta, fm_errors = _parse_frontmatter(spec_path)
    errors.extend(f"spec_{e}" for e in fm_errors)
    for key in SPEC_REQUIRED:
        if not meta.get(key):
            errors.append(f"spec_missing:{key}")
    if meta.get("status") and meta["status"] not in STATUSES:
        errors.append("spec_invalid_status")
    return meta, errors


def _plan_spec_path(repo, plan_path, meta):
    raw = meta.get("spec", "")
    if not raw:
        return None
    spec_path = Path(raw)
    if not spec_path.is_absolute():
        spec_path = plan_path.parent / spec_path
    return spec_path.resolve(strict=False)


def _validate_plan(repo, plan_path):
    plan_path = _as_repo_path(repo, plan_path)
    errors = []
    if _bad_slug_path(repo, plan_path, "plan"):
        errors.append("bad_slug")
        return Resolution(errors=errors, plan=plan_path)
    if not recognized_root(repo, plan_path, "plan"):
        errors.append("plan_outside_root")
        return Resolution(errors=errors, plan=plan_path)
    if not plan_path.exists():
        errors.append("plan_not_found")
        return Resolution(errors=errors, plan=plan_path)

    plan_class = classify_artifact(repo, plan_path)
    layout, slug = plan_class["layout"], plan_class["slug"]

    # Malformed package (AC20/BR2): a <slug>/spec or <slug>/plan with >1 basename is
    # not 1:1 with a package; refuse rather than auto-select an arbitrary artifact.
    if layout == "per-package":
        offenders = _malformed_offenders(repo, slug)
        if offenders:
            return Resolution(
                errors=errors + ["malformed_package"],
                plan=plan_path,
                candidates=offenders,
                layout=layout,
                slug=slug,
            )

    meta, fm_errors = _parse_frontmatter(plan_path)
    errors.extend(f"plan_{e}" for e in fm_errors)
    for key in PLAN_REQUIRED:
        if not meta.get(key):
            errors.append(f"plan_missing:{key}")
    if meta.get("status") and meta["status"] not in STATUSES:
        errors.append("plan_invalid_status")

    # Per-package basename must equal the frontmatter work_id (AC25/BR16); flat is exempt
    # (the resolver never compares the flat basename — AC9).
    if layout == "per-package" and meta.get("work_id") and plan_class["basename"] != meta["work_id"]:
        errors.append("basename_work_id_mismatch")

    spec_path = _plan_spec_path(repo, plan_path, meta)
    if spec_path is None:
        return Resolution(errors=errors, plan=plan_path, layout=layout, slug=slug)
    if not recognized_root(repo, spec_path, "spec"):
        errors.append("spec_outside_root")
        return Resolution(errors=errors, plan=plan_path, spec=spec_path, layout=layout, slug=slug)

    spec_class = classify_artifact(repo, spec_path)
    # Layout-class consistency (AC18/BR13): a plan may reference only a same-class spec,
    # even when the cross-class target normalizes inside a recognized root.
    if layout and spec_class["layout"] and layout != spec_class["layout"]:
        errors.append("layout_class_mismatch")
        return Resolution(errors=errors, plan=plan_path, spec=spec_path, layout=layout, slug=slug)
    # Co-location (AC8/BR3): a per-package plan resolves only to its own package's spec
    # (same slug and basename), even though the cross-package target is in a recognized root.
    if layout == "per-package" and spec_class["layout"] == "per-package":
        if spec_class["slug"] != slug or spec_class["basename"] != plan_class["basename"]:
            errors.append("colocation_violation")
            return Resolution(errors=errors, plan=plan_path, spec=spec_path, layout=layout, slug=slug)

    spec_meta, spec_errors = _validate_spec(repo, spec_path)
    errors.extend(spec_errors)
    if spec_meta and meta.get("work_id") and spec_meta.get("work_id") != meta["work_id"]:
        errors.append("work_id_mismatch")
    if (
        spec_class["layout"] == "per-package"
        and spec_meta
        and spec_meta.get("work_id")
        and spec_class["basename"] != spec_meta["work_id"]
    ):
        errors.append("basename_work_id_mismatch")

    return Resolution(
        ok=not errors,
        work_id=meta.get("work_id"),
        spec=spec_path,
        plan=plan_path,
        branch=meta.get("branch"),
        status=meta.get("status"),
        errors=errors,
        layout=layout,
        slug=slug,
    )


def _plan_files(repo):
    """Union flat plan-root globbing with per-package <slug>/plan discovery (BR4/AC7).

    The flat `(repo / PLAN_ROOT)` glob is preserved; per-package plans are added via
    `(repo / AGENTIC_ROOT).glob("*/plan/*.md")` filtered through `classify_artifact`
    (valid, non-reserved slug, role=plan), so branch-match (AC7) and explicit-spec
    pairing (AC2) see both layouts. Sorted and deduped.
    """
    repo = Path(repo).resolve(strict=False)
    plans = []
    plan_root = repo / PLAN_ROOT
    if plan_root.exists():
        plans.extend(plan_root.glob("*.md"))
    for candidate in (repo / AGENTIC_ROOT).glob("*/plan/*.md"):
        info = classify_artifact(repo, candidate)
        if info["layout"] == "per-package" and info["role"] == "plan":
            plans.append(candidate)
    return sorted(set(plans))


def _current_branch(repo):
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = proc.stdout.strip()
    return branch or None


def _changed_plans_from_git(repo):
    try:
        proc = subprocess.run(
            [
                "git", "status", "--porcelain", "--untracked-files=all",
                "--", PLAN_ROOT.as_posix(),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    plans = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        p = _as_repo_path(repo, path)
        if p.is_dir() and _is_inside(p, repo / PLAN_ROOT):
            plans.extend(sorted(p.glob("*.md")))
        elif p.suffix == ".md" and _is_inside(p, repo / PLAN_ROOT):
            plans.append(p)
    return sorted(set(plans))


def _changed_plans_from_fs(repo):
    """Per-package change-detection by filesystem scan (DP-1).

    `_changed_plans_from_git` is structurally blind to per-package plans on the basis
    of its own code, independent of any ignore rule: it restricts `git status` with the
    `-- PLAN_ROOT` pathspec (= docs/agentic-sdlc/plans) and then filters every returned
    path through `_is_inside(p, repo / PLAN_ROOT)`. Per-package plans live under
    docs/agentic-sdlc/<slug>/plan/, outside both gates, so git-status never prints them
    even in a repo with no .gitignore at all. (In the real repo the blanket `docs/*`
    ignore is the secondary reason the alternative — a .gitignore re-inclusion so
    git-status could see them — was rejected, not the reason the detector fails.)

    Because per-package artifacts are git-ignored in the real repo, "present on disk
    under a valid slug" == "changed/added" for them, so this scan never narrows.
    """
    repo = Path(repo).resolve(strict=False)
    plans = []
    for candidate in (repo / AGENTIC_ROOT).glob("*/plan/*.md"):
        info = classify_artifact(repo, candidate)
        if info["layout"] == "per-package" and info["role"] == "plan":
            plans.append(candidate)
    return sorted(set(plans))


def _finalize(result, source):
    result.source = source
    return result


def _fail(error, candidates=None):
    return Resolution(ok=False, errors=[error], candidates=candidates or [])


def _select_one(results):
    if len(results) == 1:
        return results[0]
    if len(results) > 1:
        return _fail("ambiguous_plan", [r.plan for r in results])
    return _fail("no_plan")


def _plans_for_spec(repo, spec_path):
    spec_path = _as_repo_path(repo, spec_path)
    matches = []
    for plan in _plan_files(repo):
        meta, errors = _parse_frontmatter(plan)
        if errors:
            continue
        candidate_spec = _plan_spec_path(repo, plan.resolve(strict=False), meta)
        if candidate_spec == spec_path:
            matches.append(_validate_plan(repo, plan))
    return matches


def resolve(repo, plan_path=None, spec_path=None, branch=None, changed_plans=None):
    repo = Path(repo).resolve(strict=False)

    if plan_path:
        return _finalize(_validate_plan(repo, plan_path), "explicit-plan")

    if spec_path:
        spec_path = _as_repo_path(repo, spec_path)
        _spec_meta, spec_errors = _validate_spec(repo, spec_path)
        if spec_errors:
            return Resolution(ok=False, spec=spec_path, errors=spec_errors)
        result = _select_one(_plans_for_spec(repo, spec_path))
        return _finalize(result, "explicit-spec") if result.ok else result

    branch = branch if branch is not None else _current_branch(repo)
    if branch:
        branch_matches = []
        for plan in _plan_files(repo):
            meta, _errors = _parse_frontmatter(plan)
            if meta.get("branch") == branch:
                branch_matches.append(_validate_plan(repo, plan))
        result = _select_one(branch_matches)
        if result.ok:
            return _finalize(result, "branch")
        if result.errors != ["no_plan"]:
            return result

    if changed_plans is None:
        # Union the unchanged flat git-status detector with the per-package fs-scan
        # (DP-1). Since present-on-disk == changed for git-ignored per-package plans,
        # this fallback is single-candidate-only in practice: with >=2 per-package plans
        # (or a genuinely-changed flat plan coexisting with one), the union surfaces
        # co-equal candidates and _select_one returns ambiguous_plan (AC10) — the
        # intended degradation, not a regression.
        changed_plans = sorted(
            set(_changed_plans_from_git(repo)) | set(_changed_plans_from_fs(repo))
        )
    changed_results = [_validate_plan(repo, p) for p in changed_plans]
    result = _select_one(changed_results)
    return _finalize(result, "changed-plan") if result.ok else result


_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_token(token):
    """Reduce a token to a bare filename-safe key (membership-key discipline, §6 sink-4)."""
    cleaned = _SAFE_TOKEN_RE.sub("", token)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "")
    return cleaned


def evidence_path(repo, slug, work_id):
    """Compose the canonical per-package evidence path (read-only — writes nothing).

    The slug is the slug the resolver already reported (BR14/AC23); §9 forbids
    *deriving/creating* a slug inside the resolver, not composing a path from a
    resolver-supplied one. A flat (slug-less) resolution gets no evidence path (AC11)
    → ValueError; an invalid/reserved slug or an unsafe work_id (does not sanitize to
    itself) is rejected the same way. Returns
    repo/docs/agentic-sdlc/<slug>/evidence/<work_id>.md and never creates the file or
    directory (§8 read-only contract).
    """
    if not slug or not is_valid_slug(slug):
        raise ValueError(f"invalid or flat slug: {slug!r}")
    if not work_id or _sanitize_token(work_id) != work_id:
        raise ValueError(f"unsafe work_id: {work_id!r}")
    return Path(repo).resolve(strict=False) / AGENTIC_ROOT / slug / "evidence" / f"{work_id}.md"


def fields_for(result, repo):
    fields = []
    for error in result.errors:
        fields.append(f"error={error}")
    for i, candidate in enumerate(result.candidates, start=1):
        fields.append(f"candidate_{i}={_rel(repo, candidate)}")
    if result.ok:
        fields.extend(
            [
                f"branch={result.branch}",
                f"layout={result.layout}",
                f"plan={_rel(repo, result.plan)}",
                f"resolution_source={result.source}",
                f"spec={_rel(repo, result.spec)}",
                f"status={result.status}",
                f"work_id={result.work_id}",
                "work_package_resolution=passed",
            ]
        )
        if result.slug:
            fields.append(f"slug={result.slug}")
    else:
        if result.plan:
            fields.append(f"plan={_rel(repo, result.plan)}")
        if result.spec:
            fields.append(f"spec={_rel(repo, result.spec)}")
        fields.append("work_package_resolution=failed")
    return sorted(fields)


def emit(result, repo):
    for line in fields_for(result, repo):
        print(line)


def build_parser():
    parser = argparse.ArgumentParser(description="Resolve active AGENTIC-SDLC work package.")
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--plan", default=None, help="explicit plan path")
    parser.add_argument("--spec", default=None, help="explicit spec path")
    parser.add_argument("--branch", default=None, help="override current branch")
    parser.add_argument(
        "--changed-plan",
        action="append",
        default=None,
        help="changed plan path override; repeat for tests or deterministic replay",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve(strict=False)
    result = resolve(
        repo,
        plan_path=args.plan,
        spec_path=args.spec,
        branch=args.branch,
        changed_plans=args.changed_plan,
    )
    emit(result, repo)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Resolve the active AGENTIC-SDLC spec/plan work package.

This is an identity resolver, not a content validator. `validate_artifacts.py`
still checks the markdown body. This script answers which spec/plan pair
`implementasyon-control` should audit and refuses ambiguous choices.

Output is sorted `key=value` lines. Exit 1 on failed resolution.
"""
import argparse
import subprocess
import sys
from pathlib import Path


SPEC_ROOT = Path("docs") / "agentic-sdlc" / "specs"
PLAN_ROOT = Path("docs") / "agentic-sdlc" / "plans"
STATUSES = {"draft", "reviewed", "in_progress", "ready_for_audit", "complete"}
PLAN_REQUIRED = ("work_id", "spec", "branch", "status")
SPEC_REQUIRED = ("work_id", "status")


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
    if not _is_inside(spec_path, repo / SPEC_ROOT):
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
    if not _is_inside(plan_path, repo / PLAN_ROOT):
        errors.append("plan_outside_root")
        return Resolution(errors=errors, plan=plan_path)
    if not plan_path.exists():
        errors.append("plan_not_found")
        return Resolution(errors=errors, plan=plan_path)

    meta, fm_errors = _parse_frontmatter(plan_path)
    errors.extend(f"plan_{e}" for e in fm_errors)
    for key in PLAN_REQUIRED:
        if not meta.get(key):
            errors.append(f"plan_missing:{key}")
    if meta.get("status") and meta["status"] not in STATUSES:
        errors.append("plan_invalid_status")

    spec_path = _plan_spec_path(repo, plan_path, meta)
    if spec_path is None:
        return Resolution(errors=errors, plan=plan_path)
    if not _is_inside(spec_path, repo / SPEC_ROOT):
        errors.append("spec_outside_root")
        return Resolution(errors=errors, plan=plan_path, spec=spec_path)

    spec_meta, spec_errors = _validate_spec(repo, spec_path)
    errors.extend(spec_errors)
    if spec_meta and meta.get("work_id") and spec_meta.get("work_id") != meta["work_id"]:
        errors.append("work_id_mismatch")

    return Resolution(
        ok=not errors,
        work_id=meta.get("work_id"),
        spec=spec_path,
        plan=plan_path,
        branch=meta.get("branch"),
        status=meta.get("status"),
        errors=errors,
    )


def _plan_files(repo):
    plan_root = repo / PLAN_ROOT
    if not plan_root.exists():
        return []
    return sorted(plan_root.glob("*.md"))


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
        changed_plans = _changed_plans_from_git(repo)
    changed_results = [_validate_plan(repo, p) for p in changed_plans]
    result = _select_one(changed_results)
    return _finalize(result, "changed-plan") if result.ok else result


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
                f"plan={_rel(repo, result.plan)}",
                f"resolution_source={result.source}",
                f"spec={_rel(repo, result.spec)}",
                f"status={result.status}",
                f"work_id={result.work_id}",
                "work_package_resolution=passed",
            ]
        )
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

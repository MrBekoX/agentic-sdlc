"""Shared path boundaries for eval metadata and live working directories."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def require_slug(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not SLUG_RE.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}; expected kebab-case slug")
    return value


def resolve_under(base: Path, child: str | Path, label: str, *, must_exist: bool = False) -> Path:
    """Resolve a metadata-derived child and require it to remain below the caller-owned base."""
    base = Path(base).resolve()
    raw = Path(child)
    if raw.is_absolute():
        raise ValueError(f"{label} must be relative: {child}")
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{label} escapes allowed root: {child}") from exc
    if must_exist and not candidate.exists():
        raise ValueError(f"{label} missing: {child}")
    return candidate


def require_relative_pattern(value: str, label: str) -> str:
    """Reject absolute/traversing artifact patterns before glob or disk lookup."""
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"{label} must stay below the eval working directory: {value}")
    return value


def require_link_free_tree(root: Path, label: str) -> None:
    """Reject symlinks and Windows reparse points before copying an eval fixture tree."""
    root = Path(root)
    stack = [root]
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                is_reparse = bool(getattr(info, "st_file_attributes", 0) & reparse_flag)
                if entry.is_symlink() or is_reparse:
                    relative = entry_path.relative_to(root)
                    raise ValueError(f"{label} contains link/reparse point: {relative}")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry_path)

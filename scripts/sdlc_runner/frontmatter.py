"""Runner-owned frontmatter on spec and plan files: split, parse, render.

Reads exactly like scripts/validate_artifacts.py `_frontmatter_block` and the resolver (contract
§1), so the runner, the validator and the resolver never see two different blocks in one file:
- lines are split the way str.splitlines splits them (also on a lone CR, U+2028, \\x85, ...);
- only a block that opens on the first line counts; opener and closer are whole `---` lines
  (trailing spaces aside), so an indented `---` or a `----` line is neither;
- blank and `#` lines are skipped; any other line needs `key: value` with a non-empty key, else
  it is `invalid_frontmatter_line:<line>` (reported by `parse`, skipped by `split`);
- surrounding quotes are dropped (`status: "approved"` is `approved`);
- an unterminated block is not frontmatter: the whole text is body.
The body comes back exactly as given after the closer line. Line numbers count the lines of the
text passed in; the validator reads the file with universal newlines, so a `\\r\\r\\n` (one break
after the runner's CRLF normalisation, two in the validator) shifts later numbers. The block's
keys and values never differ.
"""
from __future__ import annotations

from .textio import read_text

_DELIMITER = "---"


def _normalise(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n")


def _content(raw: str) -> str:
    """A splitlines(keepends=True) line without its line break."""
    parts = raw.splitlines()
    return parts[0] if parts else ""


def _scan(text: str):
    """(meta, body, had_block, errors) under the reading described in the module notes."""
    text = _normalise(text)
    lines = text.splitlines(keepends=True)
    if not lines or _content(lines[0]).rstrip() != _DELIMITER:
        return {}, text, False, []
    meta = {}
    errors = []
    offset = len(lines[0])
    for lineno, raw in enumerate(lines[1:], start=2):
        offset += len(raw)
        content = _content(raw)
        if content.rstrip() == _DELIMITER:
            return meta, text[offset:], True, errors
        line = content.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            errors.append("invalid_frontmatter_line:%d" % lineno)
            continue
        meta[key.strip()] = value.strip().strip("\"'")
    return {}, text, False, []


def split(text: str):
    """(meta, body, had_block). Without a terminated leading block: ({}, text, False)."""
    meta, body, had_block, _errors = _scan(text)
    return meta, body, had_block


def parse(text: str):
    """(meta, errors), the same pair validate_artifacts._frontmatter_block returns."""
    meta, _body, _had_block, errors = _scan(text)
    return meta, errors


def _value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _single_line(text: str) -> bool:
    probe = "x" + text + "x"
    return probe.splitlines() == [probe]


def render(meta: dict, body: str) -> str:
    """`---`, one `key: value` line per key in the order given, `---`, then the body ending in one newline.

    ValueError for a key or value that `split` would not read back unchanged: a line break of any
    kind, a key that is empty, padded, holds `:` or starts with `#`, a value with surrounding
    spaces or quotes.
    """
    lines = [_DELIMITER]
    for key, value in meta.items():
        key = str(key)
        text = _value(value)
        if (not key or key != key.strip() or ":" in key or key.startswith("#")
                or not _single_line(key)):
            raise ValueError("unsafe frontmatter key: %r" % key)
        if not _single_line(text):
            raise ValueError("frontmatter value for %r spans lines" % key)
        if text.strip().strip("\"'") != text:
            raise ValueError("frontmatter value for %r would not read back: %r" % (key, text))
        lines.append("%s: %s" % (key, text))
    lines.append(_DELIMITER)
    body = _normalise(body).rstrip("\n")
    return "\n".join(lines) + "\n" + (body + "\n" if body else "")


def body_text(path) -> str:
    """The text after the frontmatter block (the whole text when there is none)."""
    return split(read_text(path))[1]

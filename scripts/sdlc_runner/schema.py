"""A minimal JSON-schema subset validator (stdlib only).

Supported keywords: type (a name or a list of names), required, properties, additionalProperties
(false, true or a schema), items (one schema), enum, const, minLength, minimum, maximum, pattern.
Annotations ($schema, $id, $comment, title, description, default, examples) are ignored. Any other
keyword raises ValueError before validation, so a schema can never pass because a keyword it
relies on is silently skipped.

Errors are "<json-pointer>: <reason>" (RFC 6901 pointers; the root is the empty string), in a
stable order: the node's own checks, then properties in schema order, then extra properties
sorted, then array items.

`pattern` keeps JSON Schema's ECMA-262 meaning rather than Python's: `$` is the end of input (never
before a final newline), `\\d`, `\\w` and `\\b` are ASCII, `\\s` is JavaScript's Unicode whitespace,
and `.` stops at every line terminator. Syntax that differs between the two dialects (Python-only
groups and flags, `\\Z`, `\\A`, `\\p{..}`, empty classes, `\\S` inside a class) is refused as an
unsupported pattern rather than read differently.
"""
from __future__ import annotations

import functools
import json
import re

# JavaScript's \s (WhiteSpace and LineTerminator) as a character-class body.
_JS_SPACE = "\t\n\x0b\x0c\r \xa0  -     　﻿"
_JS_DOT = "[^\n\r  ]"
_HEX = frozenset("0123456789abcdefABCDEF")
# Escapes whose meaning is the same in ECMA-262 and in Python under re.ASCII.
_SAME_ESCAPES = frozenset("dDwWtnrvf") | frozenset("^$\\.*+?()[]{}|/-")

SUPPORTED_KEYWORDS = frozenset([
    "type", "required", "properties", "additionalProperties", "items", "enum", "const",
    "minLength", "minimum", "maximum", "pattern",
])
ANNOTATION_KEYWORDS = frozenset(["$schema", "$id", "$comment", "title", "description", "default", "examples"])
TYPE_NAMES = ("object", "array", "string", "integer", "number", "boolean", "null")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_name(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _has_type(value, name: str) -> bool:
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return _is_number(value)
    return _type_name(value) == name


def _json_equal(a, b) -> bool:
    """JSON equality: 1 == 1.0, but true is not 1 (bools fall through to the exact-type check)."""
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _ecma_escape(pattern: str, i: int, in_class: bool):
    """(Python text, next index) for the escape at pattern[i] == "\\"."""
    if i + 1 >= len(pattern):
        raise ValueError("a pattern cannot end with a backslash")
    char = pattern[i + 1]
    after = i + 2
    if char == "s":
        return (_JS_SPACE if in_class else "[" + _JS_SPACE + "]"), after
    if char == "S" and not in_class:
        return "[^" + _JS_SPACE + "]", after
    if char == "x" and len(pattern[after:after + 2]) == 2 and set(pattern[after:after + 2]) <= _HEX:
        return "\\x" + pattern[after:after + 2], after + 2
    if char == "u" and len(pattern[after:after + 4]) == 4 and set(pattern[after:after + 4]) <= _HEX:
        return "\\u" + pattern[after:after + 4], after + 4
    if char == "0" and not pattern[after:after + 1].isdigit():
        return "\\x00", after
    if char in _SAME_ESCAPES or char == "b" or (not in_class and char in "B123456789"):
        return "\\" + char, after
    raise ValueError("escape \\%s is not read the same way in ECMA-262 and Python" % char)


@functools.lru_cache(maxsize=256)
def _ecma_regex(pattern: str):
    """Compile a JSON Schema (ECMA-262) pattern to a Python regex with the same meaning."""
    out = []
    in_class = False
    i = 0
    size = len(pattern)
    while i < size:
        char = pattern[i]
        if char == "\\":
            text, i = _ecma_escape(pattern, i, in_class)
            out.append(text)
            continue
        if in_class:
            if char == "]":
                in_class = False
            elif char in "[&~|":  # literal in a JS class; Python warns about nested sets there
                char = "\\" + char
            out.append(char)
            i += 1
            continue
        if char == "[":
            start = i + 1 + (1 if pattern[i + 1:i + 2] == "^" else 0)
            if pattern[start:start + 1] == "]":
                raise ValueError("an empty character class ([] or [^]) has no Python equivalent")
            out.append(pattern[i:start])
            in_class = True
            i = start
            continue
        if char == "(" and pattern[i + 1:i + 2] == "?":
            kind = pattern[i + 2:i + 4]
            if kind[:1] not in (":", "=", "!") and kind not in ("<=", "<!"):
                raise ValueError("group syntax %r is not read the same way in ECMA-262 and Python"
                                 % pattern[i:i + 4])
            out.append("(?")
            i += 2
            continue
        out.append(r"\Z" if char == "$" else _JS_DOT if char == "." else char)
        i += 1
    if in_class:
        raise ValueError("unterminated character class")
    try:
        return re.compile("".join(out), re.ASCII)
    except re.error as exc:
        raise ValueError(str(exc)) from None


def check_schema(schema, where: str = "#") -> None:
    """Raise ValueError when `schema` uses a keyword or a value shape this validator does not support."""
    if not isinstance(schema, dict):
        raise ValueError("%s: a schema must be an object" % where)
    for key, value in schema.items():
        at = "%s/%s" % (where, _escape(key))
        if key in ANNOTATION_KEYWORDS:
            continue
        if key not in SUPPORTED_KEYWORDS:
            raise ValueError("%s: unsupported schema keyword" % at)
        if key == "type":
            names = value if isinstance(value, list) else [value]
            if not names or any(n not in TYPE_NAMES for n in names):
                raise ValueError("%s: unknown type %r" % (at, value))
        elif key == "required":
            if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
                raise ValueError("%s: must be a list of names" % at)
        elif key == "properties":
            if not isinstance(value, dict):
                raise ValueError("%s: must be an object" % at)
            for name, sub in value.items():
                check_schema(sub, "%s/%s" % (at, _escape(name)))
        elif key == "additionalProperties":
            if not isinstance(value, bool):
                check_schema(value, at)
        elif key == "items":
            check_schema(value, at)
        elif key == "enum":
            if not isinstance(value, list) or not value:
                raise ValueError("%s: must be a non-empty list" % at)
        elif key == "minLength":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("%s: must be a non-negative integer" % at)
        elif key in ("minimum", "maximum"):
            if not _is_number(value):
                raise ValueError("%s: must be a number" % at)
        elif key == "pattern":
            if not isinstance(value, str):
                raise ValueError("%s: must be a string" % at)
            try:
                _ecma_regex(value)
            except ValueError as exc:
                raise ValueError("%s: invalid pattern: %s" % (at, exc)) from None


def validate(instance, schema: dict) -> list:
    """Errors for `instance` against `schema`; an empty list means valid."""
    check_schema(schema)
    errors = []
    _validate(instance, schema, "", errors)
    return errors


def _validate(value, schema: dict, pointer: str, errors: list) -> None:
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_has_type(value, n) for n in names):
            errors.append("%s: expected %s, got %s" % (pointer, " or ".join(names), _type_name(value)))
            return
    if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
        errors.append("%s: not one of %s" % (pointer, json.dumps(schema["enum"], ensure_ascii=False)))
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append("%s: must equal %s" % (pointer, json.dumps(schema["const"], ensure_ascii=False)))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append("%s: shorter than %d characters" % (pointer, schema["minLength"]))
        if "pattern" in schema and _ecma_regex(schema["pattern"]).search(value) is None:
            errors.append("%s: does not match pattern %s" % (pointer, json.dumps(schema["pattern"])))
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: less than minimum %s" % (pointer, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s: greater than maximum %s" % (pointer, schema["maximum"]))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append("%s/%s: required property missing" % (pointer, _escape(name)))
        for name, sub in properties.items():
            if name in value:
                _validate(value[name], sub, "%s/%s" % (pointer, _escape(name)), errors)
        extra = schema.get("additionalProperties", True)
        if extra is not True:
            for name in sorted(k for k in value if k not in properties):
                child = "%s/%s" % (pointer, _escape(name))
                if extra is False:
                    errors.append("%s: additional property not allowed" % child)
                else:
                    _validate(value[name], extra, child, errors)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], "%s/%d" % (pointer, index), errors)

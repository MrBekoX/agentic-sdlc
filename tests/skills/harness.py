"""Deterministic skill/agent/workflow/hook/contract validation harness.

Why this exists: the repo had script-level tests (detect_context, validate_artifacts)
but nothing that machine-checked the SKILL.md / agent / workflow / hook / contract layer —
the part most likely to rot silently (a renamed agent, a broken `references/` link, a
hooks.json path pointing at a deleted .mjs, a flow skill that stops referencing the
work-flow it delegates to). This module is the deterministic counterpart: it parses the
artifacts and verifies their *internal wiring*, not their runtime behavior.

Design constraints (mirroring scripts/check_all.py and scripts/validate_artifacts.py):
- Pure stdlib only (json, re, pathlib). No third-party imports.
- Read-only: no file writes, no shell, no network. It validates, it never mutates.
- Output (CLI): sorted flat `key=value` lines + `skills_eval=passed|failed`. Exit 1 on error.

What it is NOT: this harness cannot prove a skill *triggers* or that the model *obeys* a
guardrail at runtime — that needs a live model (see scripts/run_trigger_eval.py and the
fixtures under fixtures/ + evals/). It proves the static substrate those evals stand on:
structure is valid, every cross-reference resolves, every contract/guardrail text is actually wired.

Two severities, like check_all.py:
- error  -> gating (a broken reference that would actually break the flow at runtime).
- warning-> reported, non-gating (doc drift worth surfacing, e.g. README claims a file
            that isn't in the tree).
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO / "skills"
AGENTS_DIR = REPO / "agents"
WORKFLOWS_DIR = REPO / "workflows"
COMMANDS_DIR = REPO / "commands"
HOOKS_DIR = REPO / "hooks"
SKILL_CONTRACTS_DIR = REPO / "contracts" / "skills"
SCRIPTS_DIR = REPO / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
EVALS_DIR = Path(__file__).resolve().parent / "evals"

# Same allow-list as scripts/check_all.py — the repo gate is intentionally broader than
# skill-creator's packaging validator (`user-invocable` / `argument-hint` are legitimate
# here and used by the flow skills). Kept in sync deliberately; the structure test asserts it.
ALLOWED_SKILL_KEYS = {
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
    "user-invocable", "argument-hint", "model", "disable-model-invocation",
}
ALLOWED_AGENT_KEYS = {"name", "description", "tools", "model"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLUGIN_ROOT_REF_RE = re.compile(r"\$\{(?:CLAUDE_PLUGIN_ROOT|PLUGIN_ROOT)\}/([A-Za-z0-9_./-]+)")


# ---------------------------------------------------------------------------
# Frontmatter / file parsing
# ---------------------------------------------------------------------------

def split_frontmatter(text):
    """Return (frontmatter, body) or (None, None) if no leading --- block.

    Identical contract to check_all.split_frontmatter so the two agree on what a
    valid frontmatter block is.
    """
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    return text[3:end], text[end + 4:]


def frontmatter_keys(fm):
    """Top-level keys, in order (a key is `^name:` at column 0 of a frontmatter line)."""
    return re.findall(r"(?m)^([A-Za-z][\w-]*):", fm)


def frontmatter_value(fm, key):
    """First single-line scalar value for `key`, or '' if absent.

    Descriptions in this repo are single long lines, so a single-line capture is
    sufficient; block scalars are not used.
    """
    m = re.search(r"(?m)^%s:\s*(.+)$" % re.escape(key), fm)
    return m.group(1).strip() if m else ""


def load_markdown_artifact(path):
    """Read a markdown artifact and return a dict with frontmatter + body, or an error marker."""
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    return {
        "path": path,
        "raw": text,
        "frontmatter": fm,
        "body": body,
        "has_frontmatter": fm is not None,
    }


# ---------------------------------------------------------------------------
# Registries — the set of real, resolvable component names
# ---------------------------------------------------------------------------

def skill_names():
    if not SKILLS_DIR.is_dir():
        return set()
    return {d.name for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()}


def agent_names():
    """Agent name from each agents/*.md frontmatter (falls back to filename stem)."""
    names = set()
    if not AGENTS_DIR.is_dir():
        return names
    for p in AGENTS_DIR.glob("*.md"):
        fm, _ = split_frontmatter(p.read_text(encoding="utf-8"))
        name = frontmatter_value(fm, "name") if fm else ""
        names.add(name or p.stem)
    return names


def workflow_names():
    """Workflow name from each workflows/*.js `meta.name` (plus the filename stem)."""
    names = set()
    if not WORKFLOWS_DIR.is_dir():
        return names
    for p in WORKFLOWS_DIR.glob("*.js"):
        text = p.read_text(encoding="utf-8")
        m = re.search(r"name:\s*'([^']+)'", text)
        if m:
            names.add(m.group(1))
        names.add(p.stem)
    return names


def workflow_agent_types():
    """Map workflow file -> set of agentType names it dispatches (integration target)."""
    out = {}
    if not WORKFLOWS_DIR.is_dir():
        return out
    for p in WORKFLOWS_DIR.glob("*.js"):
        text = p.read_text(encoding="utf-8")
        out[p.name] = set(re.findall(r"agentType:\s*'([^']+)'", text))
    return out


def command_names():
    if not COMMANDS_DIR.is_dir():
        return set()
    return {p.stem for p in COMMANDS_DIR.glob("*.md")}


def script_names():
    if not SCRIPTS_DIR.is_dir():
        return set()
    return {p.name for p in SCRIPTS_DIR.glob("*.py")}


def skill_contract_numbers():
    """Set of two-digit skill contract prefixes present, e.g. {'00','01',...,'10'}."""
    if not SKILL_CONTRACTS_DIR.is_dir():
        return set()
    out = set()
    for p in SKILL_CONTRACTS_DIR.glob("*.md"):
        m = re.match(r"^(\d{2})-", p.name)
        if m:
            out.add(m.group(1))
    return out


def registries():
    return {
        "skill": skill_names(),
        "agent": agent_names(),
        "workflow": workflow_names(),
        "command": command_names(),
        "script": script_names(),
    }


# ---------------------------------------------------------------------------
# A. Structure validation
# ---------------------------------------------------------------------------

def validate_skill_structure(skill_dir):
    """Validate one skill's SKILL.md shape. Returns (errors, warnings)."""
    errors, warnings = [], []
    name_hint = skill_dir.name
    sk = skill_dir / "SKILL.md"
    if not sk.exists():
        errors.append(f"missing_skill_md:{name_hint}")
        return errors, warnings
    art = load_markdown_artifact(sk)
    if not art["has_frontmatter"]:
        errors.append(f"no_frontmatter:{name_hint}")
        return errors, warnings
    fm, body = art["frontmatter"], art["body"] or ""

    for key in frontmatter_keys(fm):
        if key not in ALLOWED_SKILL_KEYS:
            errors.append(f"bad_frontmatter_key:{name_hint}:{key}")

    name = frontmatter_value(fm, "name")
    if not name:
        errors.append(f"no_name:{name_hint}")
    elif name != name_hint:
        errors.append(f"name_dir_mismatch:{name_hint}:{name}")
    elif not NAME_RE.match(name):
        errors.append(f"name_not_kebab:{name_hint}")

    desc = frontmatter_value(fm, "description")
    if not desc:
        errors.append(f"no_description:{name_hint}")
    else:
        if "<" in desc or ">" in desc:
            errors.append(f"angle_bracket_in_description:{name_hint}")
        if len(desc) < 40:
            warnings.append(f"thin_description:{name_hint}:{len(desc)}")

    # A skill body should carry at least one H1 title (a section anchor for the reader).
    if not re.search(r"(?m)^#\s+\S", body):
        warnings.append(f"no_h1_title:{name_hint}")

    blines = body.count("\n")
    if blines > 500:
        warnings.append(f"body_over_500:{name_hint}:{blines}")
    return errors, warnings


def validate_agent_structure(agent_path):
    """Validate one agent contract file. Returns (errors, warnings)."""
    errors, warnings = [], []
    stem = agent_path.stem
    art = load_markdown_artifact(agent_path)
    if not art["has_frontmatter"]:
        errors.append(f"agent_no_frontmatter:{stem}")
        return errors, warnings
    fm = art["frontmatter"]
    for key in frontmatter_keys(fm):
        if key not in ALLOWED_AGENT_KEYS:
            warnings.append(f"agent_unknown_key:{stem}:{key}")
    name = frontmatter_value(fm, "name")
    if not name:
        errors.append(f"agent_no_name:{stem}")
    elif name != stem:
        errors.append(f"agent_name_file_mismatch:{stem}:{name}")
    if not frontmatter_value(fm, "description"):
        errors.append(f"agent_no_description:{stem}")
    return errors, warnings


# ---------------------------------------------------------------------------
# F. Integration validation (cross-references resolve)
# ---------------------------------------------------------------------------

def _ref_resolves(ref, kind, skill_dir, reg):
    """True if a single golden cross-reference resolves to a real component/file."""
    if kind == "skill":
        return ref in reg["skill"]
    if kind == "agent":
        return ref in reg["agent"]
    if kind == "workflow":
        return ref in reg["workflow"]
    if kind == "command":
        return ref.lstrip("/") in reg["command"]
    if kind == "script":
        return ref in reg["script"]
    if kind == "file":
        return (skill_dir / ref).exists()
    return False


def validate_skill_integration(skill_dir, golden_entry, reg):
    """Check a skill's golden cross-references both APPEAR and RESOLVE. (errors, warnings)."""
    errors, warnings = [], []
    name_hint = skill_dir.name
    sk = skill_dir / "SKILL.md"
    text = sk.read_text(encoding="utf-8") if sk.exists() else ""
    for entry in golden_entry.get("must_reference", []):
        ref, kind = entry["ref"], entry["kind"]
        token = ref.lstrip("/")
        if token not in text:
            errors.append(f"missing_reference:{name_hint}:{kind}:{ref}")
        elif not _ref_resolves(ref, kind, skill_dir, reg):
            errors.append(f"dangling_reference:{name_hint}:{kind}:{ref}")
    return errors, warnings


def validate_plugin_root_refs():
    """Every ${CLAUDE_PLUGIN_ROOT}/<path> in skills+hooks must resolve to a real repo file.

    These are runtime shell/exec paths (e.g. detect_context.py, the hook .mjs files); a
    dangling one breaks the flow silently at runtime. (errors, warnings)
    """
    errors, warnings = [], []
    sources = list(SKILLS_DIR.rglob("*.md")) + [HOOKS_DIR / "hooks.json", HOOKS_DIR / "hooks-codex.json"]
    for src in sources:
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        for rel in PLUGIN_ROOT_REF_RE.findall(text):
            if not (REPO / rel).exists():
                errors.append(f"plugin_root_ref_missing:{src.relative_to(REPO).as_posix()}:{rel}")
    return errors, warnings


def _json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _json_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_strings(item)


def validate_hooks_json():
    """Hook JSON files must be valid JSON and every referenced plugin-root path must exist. (errors, warnings)."""
    errors, warnings = [], []
    for hj in (HOOKS_DIR / "hooks.json", HOOKS_DIR / "hooks-codex.json"):
        if not hj.exists():
            errors.append(f"hooks_json_missing:{hj.name}")
            continue
        try:
            data = json.loads(hj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"hooks_json_invalid:{hj.name}:{type(e).__name__}")
            continue
        refs = []
        for text in _json_strings(data):
            refs += PLUGIN_ROOT_REF_RE.findall(text)
        for rel in refs:
            if not (REPO / rel).exists():
                errors.append(f"hook_script_missing:{hj.name}:{rel}")
    return errors, warnings


def validate_workflow_agent_types(reg):
    """Every agentType a workflow dispatches must be a real agent. (errors, warnings)."""
    errors, warnings = [], []
    for fname, types in workflow_agent_types().items():
        for t in types:
            local_name = t.rsplit(":", 1)[-1]
            if t not in reg["agent"] and local_name not in reg["agent"]:
                errors.append(f"workflow_agent_missing:{fname}:{t}")
    return errors, warnings


# ---------------------------------------------------------------------------
# G. Golden / regression validation
# ---------------------------------------------------------------------------

def load_golden():
    return json.loads((GOLDEN_DIR / "skills.json").read_text(encoding="utf-8"))


def validate_golden(skill_dir, golden_entry):
    """Regression guard: name + core description trigger keywords still present. (errors, warnings)."""
    errors, warnings = [], []
    name_hint = skill_dir.name
    sk = skill_dir / "SKILL.md"
    if not sk.exists():
        errors.append(f"golden_missing_skill:{name_hint}")
        return errors, warnings
    fm, _ = split_frontmatter(sk.read_text(encoding="utf-8"))
    desc = frontmatter_value(fm or "", "description").lower()
    for kw in golden_entry.get("description_must_include", []):
        if kw.lower() not in desc:
            errors.append(f"description_drift:{name_hint}:{kw}")
    return errors, warnings


# ---------------------------------------------------------------------------
# Fixture loaders + well-formedness (B trigger, D safety)
# ---------------------------------------------------------------------------

def load_safety():
    return json.loads((FIXTURES_DIR / "safety.json").read_text(encoding="utf-8"))


def load_trigger_evalset(skill):
    p = EVALS_DIR / f"{skill}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def validate_safety_guardrails():
    """Each safety scenario's guardrail evidence must actually exist in the repo. (errors, warnings).

    This proves the guardrail is WIRED (the contract/skill/hook text is present), not that the
    model will obey it at runtime — that is a live behavioral eval.
    """
    errors, warnings = [], []
    data = load_safety()
    for scenario in data.get("scenarios", []):
        sid = scenario["id"]
        evid = scenario.get("guardrail_evidence", [])
        if not evid:
            warnings.append(f"safety_no_repo_guardrail:{sid}")
            continue
        for ev in evid:
            rel, needle = ev["file"], ev["contains"]
            fp = REPO / rel
            if not fp.exists():
                errors.append(f"safety_evidence_file_missing:{sid}:{rel}")
            elif needle.lower() not in fp.read_text(encoding="utf-8").lower():
                errors.append(f"safety_evidence_absent:{sid}:{rel}:{needle}")
    return errors, warnings


# ---------------------------------------------------------------------------
# Doc-vs-reality consistency (reported as warnings — README/docs drift)
# ---------------------------------------------------------------------------

def check_doc_consistency():
    """Surface README/doc claims that contradict the real tree. (errors, warnings)."""
    errors, warnings = [], []
    readme = REPO / "README.md"
    if readme.exists():
        txt = readme.read_text(encoding="utf-8")
        if ".claude-plugin/plugin.json" in txt and not (REPO / ".claude-plugin" / "plugin.json").exists():
            warnings.append("readme_claims_missing_plugin_manifest:.claude-plugin/plugin.json")
        if "marketplace.json" in txt and not list(REPO.rglob("marketplace.json")):
            warnings.append("readme_claims_missing_marketplace_json")
    hooks_readme = HOOKS_DIR / "README.md"
    if hooks_readme.exists():
        txt = hooks_readme.read_text(encoding="utf-8")
        # The hooks are wired in hooks.json, not a settings.json (none exists in the tree).
        if "settings.json" in txt and not list(REPO.rglob("settings.json")):
            errors.append("hooks_readme_references_missing_settings_json")
    return errors, warnings


# ---------------------------------------------------------------------------
# Aggregation + CLI
# ---------------------------------------------------------------------------

def run_all():
    """Run every deterministic check; return (errors, warnings, metrics)."""
    errors, warnings = [], []
    reg = registries()
    golden = load_golden()["skills"]
    skills = sorted(reg["skill"])

    for name in skills:
        d = SKILLS_DIR / name
        e, w = validate_skill_structure(d)
        errors += e
        warnings += w
        if name in golden:
            e, w = validate_skill_integration(d, golden[name], reg)
            errors += e
            warnings += w
            e, w = validate_golden(d, golden[name])
            errors += e
            warnings += w
        else:
            warnings.append(f"no_golden_entry:{name}")

    for ap in sorted(AGENTS_DIR.glob("*.md")) if AGENTS_DIR.is_dir() else []:
        e, w = validate_agent_structure(ap)
        errors += e
        warnings += w

    for fn in (validate_plugin_root_refs, validate_hooks_json,
               lambda: validate_workflow_agent_types(reg),
               validate_safety_guardrails, check_doc_consistency):
        e, w = fn()
        errors += e
        warnings += w

    metrics = {
        "skills_checked": len(skills),
        "agents_checked": len(reg["agent"]),
        "workflows_checked": len(reg["workflow"]),
        "skill_contracts_checked": len(skill_contract_numbers()),
    }
    return errors, warnings, metrics


def main(argv=None):
    errors, warnings, metrics = run_all()
    fields = dict(metrics)
    fields["skills_eval"] = "failed" if errors else "passed"
    lines = [f"{k}={v}" for k, v in fields.items()]
    lines += [f"warning={w}" for w in warnings]
    lines += [f"error={e}" for e in errors]
    for line in sorted(lines):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

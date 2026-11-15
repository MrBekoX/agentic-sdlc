let meta = #{
    name: "spec-plan-draft",
    description: "Internal engine of the spec/plan loop for an already-selected AGENTIC-SDLC flow: the runner stages it in the work package and launches it by path; it runs the author -> critic -> revise rounds on the staged prompts and ends with ingest-draft --assemble; not a standalone user entry point",
    when_to_use: "Launched only by the runner's draft card: the workflow tool with source script_path (the copy in draft/engine/) and the runner's args; not a standalone user entry point.",
    phases: [ #{ title: "Draft", detail: "author -> critic -> revise" } ],
};

// The Grok Build engine of the spec/plan loop (contract §10, design §5.9.2). The runner copies this
// file byte for byte to <package>/draft/engine/spec-plan-draft.rhai, records its sha256, and prints
// the launch: the workflow tool with source {type: "script_path"}, args {slug, workId, mode,
// maxRounds, packageDir, pluginRoot, python} and an agent budget that covers every call below.
// The runner staged draft/brief.md and every role prompt draft/prompts/<role>.r<N>.md of this
// visit. This script runs the rounds of flows/loops/spec-plan.json: read-only role agents, and a
// draft-scribe agent (capability "execute") that writes each output to the runner's file names and
// runs the runner commands, because a workflow script cannot write files or start programs.
// `ingest-draft --assemble` ends it; the runner believes only what the round files back.
// Rhai functions see no outer variables, so every helper takes what it needs as arguments.

fn fail(message) {
    complete(#{ ingested: false, stopReason: "", rounds: 0, error: message });
}

fn short(text) {
    if type_of(text) != "string" {
        return "";
    }
    if text.len() > 400 {
        return "..." + text.sub_string(text.len() - 400, 400);
    }
    text
}

fn only_chars(s, allowed) {
    let i = 0;
    while i < s.len() {
        if allowed.index_of(s.sub_string(i, 1)) < 0 {
            return false;
        }
        i += 1;
    }
    true
}

// scripts/resolve_work_package.py SLUG_RE, the rule the runner's packages follow.
fn is_slug(s) {
    if type_of(s) != "string" || s.len() < 1 || s.len() > 64 || s.sub_string(0, 1) == "-" {
        return false;
    }
    only_chars(s, "abcdefghijklmnopqrstuvwxyz0123456789-")
}

fn is_work_id(s) {
    let alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    if type_of(s) != "string" || s.len() < 1 || s.len() > 64 || s.index_of("..") >= 0 {
        return false;
    }
    if alnum.index_of(s.sub_string(0, 1)) < 0 {
        return false;
    }
    only_chars(s, alnum + "._-")
}

// A runner path goes into the scribe's command inside double quotes, where a quote, `$`, a backtick
// or a line break would end or expand it in Bash or PowerShell (PowerShell also takes the curly
// double quotes as quotes). Every other character is literal there. No UNC share.
fn runner_path(p) {
    if type_of(p) != "string" {
        return "";
    }
    let s = p;
    s.trim();
    if s.len() < 1 || s.len() > 1024 {
        return "";
    }
    for bad in ["\r", "\n", "\"", "`", "$", "\u0000", "\u201C", "\u201D", "\u201E"] {
        if s.index_of(bad) >= 0 {
            return "";
        }
    }
    let head = s.sub_string(0, 1);
    if s.len() >= 2 && (s.sub_string(0, 2) == "//" || s.sub_string(0, 2) == "\\\\") {
        return "";
    }
    if head == "/" {
        return s;
    }
    let letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    if s.len() >= 3 && letters.index_of(head) >= 0 && s.sub_string(1, 1) == ":"
        && (s.sub_string(2, 1) == "\\" || s.sub_string(2, 1) == "/") {
        return s;
    }
    ""
}

fn is_sep(piece) {
    piece == "/" || piece == "\\"
}

fn strip_seps(p) {
    let b = p;
    while b.len() > 0 && is_sep(b.sub_string(b.len() - 1, 1)) {
        b = b.sub_string(0, b.len() - 1);
    }
    b
}

fn join_path(base, rel) {
    let sep = "/";
    if base.index_of("\\") >= 0 && base.index_of("/") < 0 {
        sep = "\\";
    }
    let out = strip_seps(base) + sep;
    let i = 0;
    while i < rel.len() {
        let piece = rel.sub_string(i, 1);
        if piece == "/" {
            out += sep;
        } else {
            out += piece;
        }
        i += 1;
    }
    out
}

// <project><sep>docs<sep>agentic-sdlc<sep><slug>: the project the runner commands name, or "".
fn project_of(pkg, slug) {
    let tail = "/docs/agentic-sdlc/" + slug;
    let n = tail.len();
    if pkg.len() < n {
        return "";
    }
    let found = pkg.sub_string(pkg.len() - n, n);
    let i = 0;
    while i < n {
        let a = found.sub_string(i, 1);
        let b = tail.sub_string(i, 1);
        if !(a == b || (b == "/" && a == "\\")) {
            return "";
        }
        i += 1;
    }
    let project = pkg.sub_string(0, pkg.len() - n);
    // A root keeps a separator; a drive root takes `/`, because `"D:\"` would escape the quote in Bash.
    if project == "" {
        project = "/";
    } else if project.len() == 2 && project.sub_string(1, 1) == ":" {
        project += "/";
    }
    project
}

// No-progress compares issue keys target|category|where, whitespace-collapsed and case-folded as
// the runner does: Python's str.split() whitespace and str.casefold(), which lowercases each
// character (a dotless ı stays ı) and folds these few further. The runner checks the stop again
// when it assembles the result, so a remaining difference is refused, never ingested.
fn py_space(piece) {
    let ws = " \t\n\r\u000B\u000C\u001C\u001D\u001E\u001F\u0085\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u2028\u2029\u202F\u205F\u3000";
    ws.index_of(piece) >= 0
}

fn fold_char(piece) {
    if piece == "ß" || piece == "ẞ" {
        return "ss";
    }
    if piece == "ſ" {
        return "s";
    }
    if piece == "ς" {
        return "σ";
    }
    if piece == "ϐ" {
        return "β";
    }
    if piece == "ϑ" {
        return "θ";
    }
    if piece == "ϕ" {
        return "φ";
    }
    if piece == "ϖ" {
        return "π";
    }
    if piece == "ϰ" {
        return "κ";
    }
    if piece == "ϱ" {
        return "ρ";
    }
    if piece == "ϵ" {
        return "ε";
    }
    if piece == "ﬀ" {
        return "ff";
    }
    if piece == "ﬁ" {
        return "fi";
    }
    if piece == "ﬂ" {
        return "fl";
    }
    if piece == "ﬃ" {
        return "ffi";
    }
    if piece == "ﬄ" {
        return "ffl";
    }
    if piece == "ﬅ" || piece == "ﬆ" {
        return "st";
    }
    piece.to_lower()
}

fn norm_key(v) {
    if type_of(v) != "string" {
        return "";
    }
    let out = "";
    let gap = false;
    let i = 0;
    while i < v.len() {
        let piece = v.sub_string(i, 1);
        if py_space(piece) {
            gap = out != "";
        } else {
            if gap {
                out += " ";
                gap = false;
            }
            out += fold_char(piece);
        }
        i += 1;
    }
    out
}

fn issue_key(issue) {
    norm_key(issue.target) + "|" + norm_key(issue.category) + "|" + norm_key(issue.where)
}

fn count_of(list, key) {
    let n = 0;
    for k in list {
        if k == key {
            n += 1;
        }
    }
    n
}

fn same_keys(a, b) {
    if a.len() != b.len() {
        return false;
    }
    for k in a {
        if count_of(a, k) != count_of(b, k) {
            return false;
        }
    }
    true
}

// The runner's own check of a critic file (critic_errors), so a critic answer it would refuse is
// asked for again here instead of ending the loop at assemble. "" means valid.
fn critic_problem(c) {
    if type_of(c) != "map" {
        return "not an object";
    }
    if !(c.verdict == "clean" || c.verdict == "issues") {
        return "verdict";
    }
    if type_of(c.issues) != "array" {
        return "issues";
    }
    if type_of(c.coverageCheck) != "()" && type_of(c.coverageCheck) != "string" {
        return "coverageCheck";
    }
    for issue in c.issues {
        if type_of(issue) != "map" {
            return "issue";
        }
        if !(issue.target == "spec" || issue.target == "plan") {
            return "issue target";
        }
        if !(issue.severity == "critical" || issue.severity == "high" || issue.severity == "medium" || issue.severity == "low") {
            return "issue severity";
        }
        if !(issue.kind == "gap" || issue.kind == "contradiction" || issue.kind == "blocker" || issue.kind == "style") {
            return "issue kind";
        }
        if type_of(issue.category) != "string" || issue.category == "" {
            return "issue category";
        }
        if type_of(issue.whatsMissing) != "string" || issue.whatsMissing == "" {
            return "issue whatsMissing";
        }
        if type_of(issue.where) != "string" {
            return "issue where";
        }
        if type_of(issue.fix) != "string" {
            return "issue fix";
        }
    }
    ""
}

fn is_blocking(issue) {
    issue.severity == "critical" || issue.severity == "high" || issue.kind == "contradiction" || issue.kind == "blocker"
}

fn clean_points(points) {
    let out = [];
    if type_of(points) != "array" {
        return out;
    }
    for p in points {
        if type_of(p) != "map" || type_of(p.id) != "string" || type_of(p.question) != "string"
            || type_of(p.options) != "array" || type_of(p.recommendation) != "string" {
            continue;
        }
        let id = p.id;
        id.trim();
        let question = p.question;
        question.trim();
        if id == "" || question == "" {
            continue;
        }
        let options = [];
        for o in p.options {
            if type_of(o) == "string" {
                options.push(o);
            }
        }
        out.push(#{ id: p.id, question: p.question, options: options, recommendation: p.recommendation });
    }
    out
}

fn normalize_body(text) {
    let parts = text.split("\r\n");
    let out = "";
    let i = 0;
    while i < parts.len() {
        if i > 0 {
            out += "\n";
        }
        out += parts[i];
        i += 1;
    }
    while out.len() > 0 && out.sub_string(out.len() - 1, 1) == "\n" {
        out = out.sub_string(0, out.len() - 1);
    }
    out + "\n"
}

// A marker line the text does not contain, so the scribe can tell where the text ends.
fn marker_for(body) {
    let k = 0;
    while body.index_of("=====8<===== " + k.to_string()) >= 0 {
        k += 1;
    }
    "=====8<===== " + k.to_string()
}

// flows/loops/spec-plan.json, which the engine parity test pins this table to.
fn modes_table() {
    #{
        "spec+plan": #{ artifacts: ["spec", "plan"], first: [["author-spec", "spec"], ["author-plan", "plan"]], revise: [["author-spec", "revise"], ["author-plan", "revise"]] },
        "spec": #{ artifacts: ["spec"], first: [["author-spec", "spec"]], revise: [["author-spec", "revise"]] },
        "plan": #{ artifacts: ["plan"], first: [["author-plan", "plan"]], revise: [["author-plan", "revise"]] },
        "bugfix-plan": #{ artifacts: ["plan"], first: [["author-plan", "bugfix-plan"]], revise: [["author-plan", "revise"]] },
    }
}

fn author_schema() {
    #{
        "type": "object",
        "required": ["draftMarkdown", "decisionPoints"],
        "properties": #{
            "draftMarkdown": #{ "type": "string" },
            "decisionPoints": #{
                "type": "array",
                "items": #{
                    "type": "object",
                    "required": ["id", "question", "options", "recommendation"],
                    "properties": #{
                        "id": #{ "type": "string" },
                        "question": #{ "type": "string" },
                        "options": #{ "type": "array", "items": #{ "type": "string" } },
                        "recommendation": #{ "type": "string" },
                    },
                },
            },
        },
    }
}

// flows/schemas/critic.schema.json (the runner validates the written file against it again).
fn critic_schema() {
    #{
        "type": "object",
        "required": ["verdict", "issues"],
        "properties": #{
            "verdict": #{ "type": "string", "enum": ["clean", "issues"] },
            "issues": #{
                "type": "array",
                "items": #{
                    "type": "object",
                    "required": ["target", "category", "severity", "kind", "whatsMissing", "where", "fix"],
                    "properties": #{
                        "target": #{ "type": "string", "enum": ["spec", "plan"] },
                        "category": #{ "type": "string", "minLength": 1 },
                        "severity": #{ "type": "string", "enum": ["critical", "high", "medium", "low"] },
                        "kind": #{ "type": "string", "enum": ["gap", "contradiction", "blocker", "style"] },
                        "whatsMissing": #{ "type": "string", "minLength": 1 },
                        "where": #{ "type": "string" },
                        "fix": #{ "type": "string" },
                    },
                },
            },
            "coverageCheck": #{ "type": "string" },
        },
    }
}

fn scribe_schema() {
    #{
        "type": "object",
        "required": ["action"],
        "properties": #{
            "action": #{ "type": "string", "enum": ["write", "command", "refused"] },
            "path": #{ "type": "string" },
            "bytes": #{ "type": "integer" },
            "exitCode": #{ "type": "integer" },
            "output": #{ "type": "string" },
            "reason": #{ "type": "string" },
        },
    }
}

fn role_prompt(pkg, role, n) {
    "Read \"" + join_path(pkg, "draft/prompts/" + role + ".r" + n.to_string() + ".md")
        + "\" and follow it: it is your complete instruction for this card (the files to read, what to return and the mode rules).\n"
}

fn run_scribe(prompt, label) {
    let r = agent(prompt, #{
        label: label,
        phase: "Draft",
        capability_mode: "execute",
        output_schema: scribe_schema(),
        agent_type: "agentic-sdlc:draft-scribe",
    });
    if type_of(r) != "map" || r.success != true || type_of(r.output) != "map" {
        return #{ ok: false, error: "spec-plan-draft: the scribe failed for " + label };
    }
    #{ ok: true, report: r.output }
}

fn write_file(pkg, context, rel, text) {
    let path = join_path(pkg, rel);
    let body = normalize_body(text);
    let marker = marker_for(body);
    let prompt = "Write call.\n" + context + "\nPath: \"" + path + "\"\n"
        + "The text is every line between the two marker lines below; the file ends with exactly one newline.\n"
        + marker + "\n" + body + marker;
    let r = run_scribe(prompt, "scribe:write:" + rel);
    if !r.ok {
        return r;
    }
    if r.report.action != "write" {
        return #{ ok: false, error: "spec-plan-draft: the scribe did not write " + rel + ": " + short(r.report.reason) };
    }
    #{ ok: true }
}

fn run_command(run, subcommand, extra, label) {
    let argv = [run.python, "-B", run.script, "--project", run.project, "--slug", run.slug, subcommand];
    let display = "\"" + run.python + "\" -B \"" + run.script + "\" --project \"" + run.project + "\" --slug "
        + run.slug + " " + subcommand;
    for x in extra {
        argv.push(x);
        display += " " + x;
    }
    let prompt = "Command call.\n" + run.context + "\nRun exactly this runner command: " + display
        + "\nThe same command as an argument list (JSON): " + json_encode(argv);
    let r = run_scribe(prompt, label);
    if !r.ok {
        return r;
    }
    if r.report.action != "command" {
        return #{ ok: false, error: "spec-plan-draft: the scribe did not run " + subcommand + ": " + short(r.report.reason) };
    }
    #{ ok: true, report: r.report }
}

// One author call and the scribe's write of its draft; the result carries the cleaned decision points.
fn run_author(run, role, n, author_mode) {
    let artifact = if role == "author-spec" { "spec" } else { "plan" };
    let label = if n == 0 { "author:" } else { "author-revise:" };
    label += artifact + ":r" + n.to_string();
    let prompt = role_prompt(run.pkg, role, n)
        + "Return through the structured-output tool: draftMarkdown = the complete " + author_mode
        + " draft body (no frontmatter), decisionPoints = every open decision point of this draft (an empty list when there is none).";
    let out = agent(prompt, #{
        label: label,
        phase: "Draft",
        capability_mode: "read-only",
        output_schema: author_schema(),
        agent_type: "agentic-sdlc:spec-plan-author",
    });
    if type_of(out) != "map" || out.success != true || type_of(out.output) != "map" {
        return #{ ok: false, error: "spec-plan-draft: the author failed for " + label };
    }
    let draft = out.output.draftMarkdown;
    if type_of(draft) != "string" {
        return #{ ok: false, error: "spec-plan-draft: " + label + " returned an empty draft" };
    }
    let check = draft;
    check.trim();
    if check == "" {
        return #{ ok: false, error: "spec-plan-draft: " + label + " returned an empty draft" };
    }
    let w = write_file(run.pkg, run.context, "draft/" + artifact + ".r" + n.to_string() + ".md", draft);
    if !w.ok {
        return w;
    }
    #{ ok: true, points: clean_points(out.output.decisionPoints) }
}

// --- arguments ---------------------------------------------------------------------------------

let a = args;
if type_of(a) == "string" {
    try {
        a = parse_json(a);
    } catch (err) {
        fail("spec-plan-draft: args is a non-JSON string");
    }
}
if type_of(a) != "map" {
    fail("spec-plan-draft: args must be a map with the runner's launch keys");
}
let slug = a.slug;
if !is_slug(slug) {
    fail("spec-plan-draft: invalid runner args: slug");
}
if !is_work_id(a.workId) {
    fail("spec-plan-draft: invalid runner args: workId");
}
let mode = a.mode;
if type_of(mode) != "string" || !(mode == "spec+plan" || mode == "spec" || mode == "plan" || mode == "bugfix-plan") {
    fail("spec-plan-draft: invalid runner args: mode");
}
let max_rounds = 3;
let hard_max_rounds = 5;
if type_of(a.maxRounds) == "i64" {
    if a.maxRounds < 1 || a.maxRounds > hard_max_rounds {
        fail("spec-plan-draft: invalid runner args: maxRounds (1..5)");
    }
    max_rounds = a.maxRounds;
} else if type_of(a.maxRounds) != "()" {
    fail("spec-plan-draft: invalid runner args: maxRounds (1..5)");
}
let plugin_root = runner_path(a.pluginRoot);
if plugin_root == "" {
    fail("spec-plan-draft: invalid runner args: pluginRoot");
}
let python = runner_path(a.python);
if python == "" {
    fail("spec-plan-draft: invalid runner args: python");
}
let pkg_arg = runner_path(a.packageDir);
if pkg_arg == "" {
    fail("spec-plan-draft: invalid runner args: packageDir");
}
let pkg = strip_seps(pkg_arg);
let project = project_of(pkg, slug);
if project == "" {
    fail("spec-plan-draft: invalid runner args: packageDir (not docs/agentic-sdlc/" + slug + ")");
}
let run = #{
    slug: slug,
    python: python,
    script: join_path(plugin_root, "scripts/sdlc.py"),
    project: project,
    pkg: pkg,
    context: "Plugin root (<runtime-root>): \"" + plugin_root + "\"\nPackage: \"" + pkg + "\"",
};
let engine_id = "grok-workflow";
let spec = modes_table()[mode];

// --- the rounds --------------------------------------------------------------------------------

phase("Draft");
let points = #{};
for pair in spec.first {
    let r = run_author(run, pair[0], 0, pair[1]);
    if !r.ok {
        fail(r.error);
    }
    points["r0:" + pair[0]] = r.points;
}

let marks = [];
let previous_keys = [];
let have_previous = false;
let stop_reason = "";
let rounds = 0;
let n = 1;
while n <= max_rounds {
    let check = run_command(run, "draft-check", ["--round", n.to_string()], "scribe:draft-check:r" + n.to_string());
    if !check.ok {
        fail(check.error);
    }
    if check.report.exitCode != 0 {
        fail("spec-plan-draft: draft-check --round " + n.to_string() + " exited " + check.report.exitCode.to_string()
            + ": " + short(check.report.output));
    }
    let validator = "";
    if type_of(check.report.output) == "string" {
        if check.report.output.index_of("draft_check=clean round=" + n.to_string()) >= 0 {
            validator = "clean";
        } else if check.report.output.index_of("draft_check=blocking round=" + n.to_string()) >= 0 {
            validator = "blocking";
        }
    }
    if validator == "" {
        fail("spec-plan-draft: draft-check --round " + n.to_string() + " printed no result line: " + short(check.report.output));
    }

    let label = "critic:" + mode + ":r" + n.to_string();
    if n == max_rounds {
        label += ":final";
    }
    // A critic answer the runner would refuse is asked for once more, as the runner-driven loop
    // does (role_reentry 2); a second one ends the run.
    let critique = #{};
    let have_critique = false;
    let problem = "";
    let attempt = 1;
    while attempt <= 2 && !have_critique {
        let call_label = label;
        let note = "";
        if attempt > 1 {
            call_label += ":retry";
            note = " Your previous answer was refused (" + problem + "): every issue needs all seven fields with their allowed values.";
        }
        let answer = agent(role_prompt(run.pkg, "critic", n) + "Return the critic object through the structured-output tool." + note, #{
            label: call_label,
            phase: "Draft",
            capability_mode: "read-only",
            output_schema: critic_schema(),
            agent_type: "agentic-sdlc:spec-plan-critic",
        });
        if type_of(answer) != "map" || answer.success != true || type_of(answer.output) != "map" {
            fail("spec-plan-draft: the critic failed for " + call_label);
        }
        problem = critic_problem(answer.output);
        if problem == "" {
            critique = answer.output;
            have_critique = true;
        }
        attempt += 1;
    }
    if !have_critique {
        fail("spec-plan-draft: " + label + " returned no valid critic object (" + problem + ")");
    }
    let w = write_file(run.pkg, run.context, "draft/critic.r" + n.to_string() + ".json", json_encode(critique));
    if !w.ok {
        fail(w.error);
    }
    marks.push("fresh");

    let keys = [];
    let any_blocking = false;
    for issue in critique.issues {
        keys.push(issue_key(issue));
        if is_blocking(issue) {
            any_blocking = true;
        }
    }
    if critique.verdict == "clean" && !any_blocking && validator == "clean" {
        stop_reason = "clean";
    } else if have_previous && same_keys(keys, previous_keys) {
        stop_reason = "no-progress";
    } else if n >= max_rounds {
        stop_reason = "max-rounds";
    }
    rounds = n;
    log("round " + n.to_string() + ": critic " + critique.verdict + ", validator " + validator);
    if stop_reason != "" {
        break;
    }
    previous_keys = keys;
    have_previous = true;
    for pair in spec.revise {
        let r = run_author(run, pair[0], n, pair[1]);
        if !r.ok {
            fail(r.error);
        }
        points["r" + n.to_string() + ":" + pair[0]] = r.points;
    }
    n += 1;
}

// The ingested drafts are the round before the stop; their authors' decision points go with them.
let final_points = [];
let seen = [];
for pair in spec.first {
    let key = "r" + (rounds - 1).to_string() + ":" + pair[0];
    if type_of(points[key]) == "array" {
        for p in points[key] {
            if count_of(seen, p.id) == 0 {
                seen.push(p.id);
                final_points.push(p);
            }
        }
    }
}
let loop_json = json_encode(#{
    schema: "agentic-sdlc/loop@1",
    engine: engine_id,
    mode: mode,
    rounds: rounds,
    stopReason: stop_reason,
    critic: marks,
    decisionPoints: final_points,
});
let w = write_file(run.pkg, run.context, "draft/loop.json", loop_json);
if !w.ok {
    fail(w.error);
}
let ingest = run_command(run, "ingest-draft", ["--assemble"], "scribe:ingest-draft");
if !ingest.ok {
    fail(ingest.error);
}
// The exit code decides: a success prints `ingested=` and then the next step's card, which can be
// longer than the tail the scribe reports.
if ingest.report.exitCode == 0 {
    complete(#{ ingested: true, stopReason: stop_reason, rounds: rounds });
}
complete(#{ ingested: false, stopReason: stop_reason, rounds: rounds, error: short(ingest.report.output) });

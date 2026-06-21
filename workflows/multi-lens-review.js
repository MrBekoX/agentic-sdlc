export const meta = {
  name: 'multi-lens-review',
  description: 'Adversarial multi-lens review: fan out one specialist per lens to find issues, then spawn skeptics to refute each finding so only confirmed ones survive; presets security and quality. Internal higher-rigor workflow, not a standalone user entry point',
  phases: [{ title: 'Find' }, { title: 'Verify' }],
}
// args: { preset?: 'security'|'quality', scope: <diff|files|description>, verifyVotes?: number, maxVerify?: number }
//
// Why this exists: the baseline review skills fan out one specialist per lens from the main
// loop and the main loop synthesizes (cheap, conversational). This workflow is the *higher-rigor*
// tier for when a wrong call is costly: it adds an adversarial verify pass — each finding is
// challenged by independent skeptics, and only findings that survive are kept. Same family as
// spec-plan-draft's author->critic loop, just find -> refute instead of draft -> critique.
//
// Arg-carriage guard mirrors spec-plan-draft: the runtime may deliver `args` as an object OR a
// JSON string. Parse defensively and FAIL LOUD on empty scope instead of reviewing nothing.

// agentType literals live here so the deterministic harness (validate_workflow_agent_types)
// can confirm every dispatched role resolves to a real agents/ contract.
const PRESETS = {
  security: {
    lenses: [
      { key: 'injection',  agentType: 'agentic-sdlc:security-reviewer' },
      { key: 'authz-IDOR', agentType: 'agentic-sdlc:security-reviewer' },
      { key: 'secrets',    agentType: 'agentic-sdlc:security-reviewer' },
      { key: 'auth',       agentType: 'agentic-sdlc:security-reviewer' },
    ],
    find: 'Audit the scope ONLY through the {lens} lens. Trace each untrusted input from its entry point to the dangerous sink; report only findings that carry a concrete location and an input->sink path. Mask any secret value as ***MASKED***; never print a real secret.',
  },
  quality: {
    lenses: [
      { key: 'correctness',    agentType: 'agentic-sdlc:code-reviewer' },
      { key: 'duplication',    agentType: 'agentic-sdlc:code-reviewer' },
      { key: 'error-handling', agentType: 'agentic-sdlc:code-reviewer' },
      { key: 'architecture',   agentType: 'agentic-sdlc:software-architect' },
    ],
    find: 'Review the scope ONLY through the {lens} lens. Report only findings that touch correctness, the stated requirement, or maintainability, each with file:line and the concrete consequence it carries. Do not manufacture nits.',
  },
}

function resolveArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try { a = JSON.parse(a) }
    catch (e) { throw new Error('multi-lens-review: args is a non-JSON string; cannot read preset/scope: ' + e.message) }
  }
  a = a || {}
  const preset = a.preset || 'security'
  if (!PRESETS[preset]) {
    throw new Error('multi-lens-review: unknown preset "' + preset + '" — use "security" or "quality".')
  }
  const scope = a.scope
  const isEmpty = scope === undefined || scope === null
    || (typeof scope === 'object' && Object.keys(scope).length === 0)
    || (typeof scope === 'string' && scope.trim() === '')
  if (isEmpty) {
    throw new Error('multi-lens-review: empty/missing `scope` — refusing to review nothing. '
      + 'Pass the diff, files, or description as args.scope (object or string).')
  }
  const votes = Number.isInteger(a.verifyVotes) && a.verifyVotes > 0 ? a.verifyVotes : 3
  const maxVerify = Number.isInteger(a.maxVerify) && a.maxVerify > 0 ? a.maxVerify : 30
  return { preset, cfg: PRESETS[preset], scopeStr: typeof scope === 'string' ? scope : JSON.stringify(scope), votes, maxVerify }
}

const FINDINGS = { type: 'object', required: ['findings'], properties: {
  findings: { type: 'array', items: { type: 'object', required: ['title', 'severity'], properties: {
    title: { type: 'string' },
    severity: { enum: ['critical', 'high', 'medium', 'low'] },
    location: { type: 'string' },
    evidence: { type: 'string' } } } } } }
const VERDICT = { type: 'object', required: ['refuted'], properties: {
  refuted: { type: 'boolean' }, reason: { type: 'string' } } }

const { preset, cfg, scopeStr, votes, maxVerify } = resolveArgs(args)
const SEV = { critical: 0, high: 1, medium: 2, low: 3 }

// --- Find: one specialist per lens, concurrently ---
phase('Find')
const perLens = await parallel(cfg.lenses.map((L) => () =>
  agent(
    cfg.find.replace('{lens}', L.key) + `\nScope:\n${scopeStr}`,
    { label: `find:${L.key}`, phase: 'Find', schema: FINDINGS, agentType: L.agentType },
  ).then((r) => (((r && r.findings) || []).map((f) => ({ ...f, lens: L.key, agentType: L.agentType }))))
))

// Barrier is justified here: dedup across ALL lenses before the expensive verify fan-out, so the
// same issue surfaced by two lenses is challenged once, not twice.
const seen = new Set()
const findings = []
for (const f of perLens.filter(Boolean).flat()) {
  const key = ((f.title || '') + '|' + (f.location || '')).toLowerCase().trim()
  if (seen.has(key)) continue
  seen.add(key)
  findings.push(f)
}
if (!findings.length) {
  return { preset, lensCount: cfg.lenses.length, findingCount: 0, confirmed: [], dropped: [], unverified: [] }
}

// Bound the verify fan-out by severity; never drop silently — report what was not verified.
findings.sort((a, b) => (SEV[a.severity] === undefined ? 9 : SEV[a.severity]) - (SEV[b.severity] === undefined ? 9 : SEV[b.severity]))
const toVerify = findings.slice(0, maxVerify)
const unverified = findings.slice(maxVerify)
if (unverified.length) {
  log(`verify cap ${maxVerify}: ${unverified.length} lower-severity finding(s) reported unverified, not dropped`)
}

// --- Verify: independent skeptics try to refute each finding ---
phase('Verify')
const judged = await parallel(toVerify.map((f) => () =>
  parallel(Array.from({ length: votes }, (_unused, i) => () =>
    agent(
      `Adversarially check this ${preset} finding. Set refuted=true ONLY if you can show it is a false positive — `
      + `the input is unreachable, the path is already mitigated, or it is not a real defect. If it holds, or you are `
      + `unsure, set refuted=false (keep it). Conservative on doubt: a real issue dropped is worse than one re-examined.\n`
      + `Finding: ${f.title}\nSeverity: ${f.severity}\nLocation: ${f.location || 'n/a'}\nEvidence: ${f.evidence || 'n/a'}\nScope:\n${scopeStr}`,
      { label: `verify:${f.lens}:${i}`, phase: 'Verify', schema: VERDICT, agentType: f.agentType },
    )
  )).then((vs) => {
    const valid = vs.filter(Boolean)
    return { finding: f, refutedVotes: valid.filter((v) => v.refuted).length, totalVotes: valid.length }
  })
))

const confirmed = []
const dropped = []
for (const j of judged.filter(Boolean)) {
  // Keep unless a strict majority refuted (a tie keeps the finding — conservative for security).
  if (j.totalVotes > 0 && j.refutedVotes * 2 > j.totalVotes) {
    dropped.push({ title: j.finding.title, lens: j.finding.lens, severity: j.finding.severity, refutedVotes: j.refutedVotes, totalVotes: j.totalVotes })
  } else {
    confirmed.push(j.finding)
  }
}

return {
  preset,
  lensCount: cfg.lenses.length,
  findingCount: findings.length,
  confirmed,
  dropped,
  unverified: unverified.map((u) => ({ title: u.title, lens: u.lens, severity: u.severity })),
}

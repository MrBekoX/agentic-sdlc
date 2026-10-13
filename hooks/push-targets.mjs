// Pure push argv/config resolution. No shell, filesystem or remote access occurs here.
// The caller supplies bounded local state; an unknown destination is never called verified safe.
export const PUSH_CONFIG_PATTERN = '^(push\\.default|remote\\.pushdefault|remote\\..*\\.(push|mirror)|branch\\..*\\.(remote|pushremote|merge))$';

function configKey(key) {
  const parts = String(key).split('.');
  parts[0] = parts[0].toLowerCase();
  parts[parts.length - 1] = parts[parts.length - 1].toLowerCase();
  return parts.join('.'); // subsection (branch/remote name) is case-sensitive
}

export function parsePushArguments(args) {
  const options = { refs: [], remote: null, force: false, lease: false, all: false,
    mirror: false, remove: false, tags: false, prune: false, unknown: false };
  const positional = [];
  let repoOption = null;
  let end = false;
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (!end && arg === '--') { end = true; continue; }
    if (!end && arg.startsWith('--')) {
      const eq = arg.indexOf('=');
      const name = eq < 0 ? arg : arg.slice(0, eq);
      const value = eq < 0 ? null : arg.slice(eq + 1);
      if (['--repo', '--push-option', '--receive-pack', '--exec', '--recurse-submodules'].includes(name)) {
        const operand = value === null ? args[++i] : value;
        if (operand === undefined) options.unknown = true;
        if (name === '--repo') repoOption = operand;
      } else if (name === '--force') options.force = true;
      else if (name === '--no-force') options.force = false;
      else if (name === '--force-with-lease') options.lease = true;
      else if (name === '--no-force-with-lease') options.lease = false;
      else if (name === '--all' || name === '--branches') options.all = true;
      else if (name === '--no-all' || name === '--no-branches') options.all = false;
      else if (name === '--mirror') options.mirror = true;
      else if (name === '--no-mirror') options.mirror = false;
      else if (name === '--delete') options.remove = true;
      else if (name === '--no-delete') options.remove = false;
      else if (name === '--tags') options.tags = true;
      else if (name === '--no-tags') options.tags = false;
      else if (name === '--prune') options.prune = true;
      else if (name === '--no-prune') options.prune = false;
      // Lease/signed accept optional values only via '='; the next token is still positional.
      else if (!/^--(?:no-)?(?:signed|atomic|dry-run|follow-tags|force-if-includes|ipv4|ipv6|quiet|verbose|progress|thin|verify|porcelain)$/.test(name)) {
        options.unknown = true;
      }
      continue;
    }
    if (!end && arg.startsWith('-') && arg !== '-') {
      for (let j = 1; j < arg.length; j += 1) {
        const flag = arg[j];
        if (flag === 'f') options.force = true;
        else if (flag === 'd') options.remove = true;
        else if (flag === 'o') {
          if (j + 1 === arg.length && args[++i] === undefined) options.unknown = true;
          break; // attached or following push-option data is never a destination
        } else if (!'nvq4u'.includes(flag) && flag !== '6') options.unknown = true;
      }
      continue;
    }
    positional.push(arg);
  }
  options.remote = positional.shift() || repoOption;
  options.refs = positional;
  return options;
}

function protectedName(ref) {
  const name = String(ref || '').replace(/^refs\/heads\//, '');
  return /^(main|master)$/i.test(name) ? name.toLowerCase() : null;
}

function patternCapture(pattern, value) {
  const star = pattern.indexOf('*');
  if (star < 0) return pattern === value ? '' : null;
  if (pattern.indexOf('*', star + 1) >= 0) return null;
  const prefix = pattern.slice(0, star);
  const suffix = pattern.slice(star + 1);
  return value.startsWith(prefix) && value.endsWith(suffix) && value.length >= prefix.length + suffix.length
    ? value.slice(prefix.length, value.length - suffix.length) : null;
}

// The existing branch policy is case-insensitive; preserve concrete spellings until
// Git's case-sensitive destination exclusions have run. This domain is always 80 refs.
const protectedRefs = ['main', 'master'].flatMap((name) =>
  [...name].reduce((words, ch) => words.flatMap((word) => [word + ch, word + ch.toUpperCase()]), [''])
    .map((word) => `refs/heads/${word}`));

function gitBoolean(value) {
  if (value === undefined) return false;
  if (value === null) return true; // valueless config, normalized by the hook reader too
  const text = String(value);
  const word = text.toLowerCase();
  if (['true', 'yes', 'on'].includes(word)) return true;
  if (['false', 'no', 'off', ''].includes(word)) return false;
  // Git accepts signed base-0 integers, with binary k/m/g scaling, as booleans.
  const numeric = text.replace(/^[\t\n\v\f\r ]+/, '');
  const match = /^([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([kKmMgG]?)$/.exec(numeric);
  if (!match || match[0].length !== numeric.length) return null;
  const raw = match[2];
  const radix = /^0x/i.test(raw) ? 16 : raw.length > 1 && raw[0] === '0' ? 8 : 10;
  const digits = (radix === 16 ? raw.slice(2) : raw).replace(/^0+/, '') || '0';
  if (digits.length > ({ 16: 8, 8: 11, 10: 10 })[radix]) return null;
  let integer = BigInt((radix === 16 ? '0x' : radix === 8 ? '0o' : '') + digits);
  integer *= ({ '': 1n, k: 1024n, m: 1048576n, g: 1073741824n })[match[3].toLowerCase()];
  if (match[1] === '-') integer = -integer;
  if (integer < -2147483648n || integer > 2147483647n) return null;
  return integer !== 0n;
}

export function resolvePushTargets(invocation, state = {}) {
  const options = parsePushArguments(invocation.args);
  const configs = new Map();
  for (const [rawKey, value] of [...(state.config || []), ...(invocation.inlineConfig || [])]) {
    const key = configKey(rawKey);
    if (!configs.has(key)) configs.set(key, []);
    configs.get(key).push(value);
  }
  const values = (key) => configs.get(configKey(key)) || [];
  const last = (key) => values(key).at(-1);
  const branch = state.branch || '';
  const branchRemote = last(`branch.${branch}.remote`);
  const remote = options.remote || last(`branch.${branch}.pushRemote`) || last('remote.pushDefault')
    || branchRemote || (state.remotes?.length === 1 ? state.remotes[0] : 'origin');
  const mode = last('push.default') || 'simple';
  const refs = state.refs || [];
  const refSet = new Set(refs);
  const configured = values(`remote.${remote}.push`);
  const activeSpecs = options.refs.length ? options.refs : (!options.all && !options.tags ? configured : []);
  const negatives = activeSpecs.filter((ref) => ref.startsWith('^')).map((ref) => ref.slice(1));
  // Compute exclusions once, not for every positive candidate: both lists can be large.
  const excludedDestinations = new Set(protectedRefs.filter((ref) =>
    negatives.some((pattern) => patternCapture(pattern, ref) !== null)));
  const targets = new Set();
  let force = options.force || options.lease;
  let unresolved = options.unknown || invocation.readContextKnown === false || !state.available
    || [...invocation.args, ...(invocation.inlineConfig || []).flat()].some((value) => /[$`]/.test(value));
  let pruneDeletion = false;
  const add = (ref, forced = false) => {
    const name = protectedName(ref);
    const destination = String(ref).startsWith('refs/') ? ref : `refs/heads/${ref}`;
    // PUSH negatives filter the final destination table, after mapping and pruning.
    if (name && !excludedDestinations.has(destination)) {
      targets.add(name); force ||= forced;
      return true;
    }
    return false;
  };
  const currentRef = branch ? `refs/heads/${branch}` : '';
  const localMatches = (source) => {
    const candidates = [...new Set([source, `refs/${source}`, `refs/tags/${source}`,
      `refs/heads/${source}`, `refs/remotes/${source}`, `refs/remotes/${source}/HEAD`])]
      .filter((ref) => refSet.has(ref));
    const strong = candidates.filter((ref) => ref.startsWith('refs/heads/') || ref.startsWith('refs/tags/')
      || ref === source || ref === `refs/${source}`);
    return strong.length ? strong : candidates;
  };
  const fullSource = (source) => {
    if (source === 'HEAD') return currentRef;
    if (!source) return '';
    const matches = localMatches(source);
    if (matches.length === 1) return matches[0];
    if (matches.length > 1) { unresolved = true; return ''; }
    unresolved = true; // arbitrary object expressions/unavailable refs are not verified ref names
    if (source.startsWith('refs/')) return source;
    if (/^(heads|tags|remotes)\//.test(source)) return `refs/${source}`;
    return `refs/heads/${source}`;
  };
  const configuredMirror = gitBoolean(last(`remote.${remote}.mirror`));
  if (configuredMirror === null) unresolved = true;
  const mirror = options.mirror || configuredMirror === true;
  if (mirror) {
    // A missing LOCAL main cannot exclude deletion of a REMOTE main by --mirror.
    targets.add('main'); targets.add('master');
    return { targets: [...targets], force: true, mirror: true, unresolved };
  }
  const matching = (forced = false) => {
    if (!state.refsKnown) unresolved = true;
    for (const ref of protectedRefs) {
      // Matching/all can remove a REMOTE branch with no corresponding local ref.
      if (refSet.has(ref) || options.prune) {
        const selected = add(ref, forced);
        if (options.prune && selected) pruneDeletion = true;
      }
    }
  };
  const configNegatives = configured.filter((ref) => ref.startsWith('^')).map((ref) => ref.slice(1));
  const configNegativeNames = new Set(configNegatives.filter((ref) => !ref.includes('*')));
  const configNegativePatterns = configNegatives.filter((ref) => ref.includes('*'));
  const configRequests = configured.filter((ref) => !ref.startsWith('^')).map((raw) => {
    const clean = raw.startsWith('+') ? raw.slice(1) : raw;
    const colon = clean.indexOf(':');
    return { src: colon < 0 ? clean : clean.slice(0, colon),
      dst: colon < 0 ? null : clean.slice(colon + 1), matching: clean === ':',
      pattern: clean.includes('*'), force: raw.startsWith('+') };
  });
  const mappingCache = new Map();
  // Account string work, not elapsed time, so the same input has the same boundary.
  // Budget exhaustion is UNKNOWN, distinct from Git's null/no-mapping result.
  let queryWork = 8 * 1024 * 1024;
  const spend = (...texts) => {
    queryWork -= texts.reduce((size, value) => size + value.length, 0);
    return queryWork >= 0;
  };
  const unknownMapping = (source) => {
    unresolved = true;
    mappingCache.set(source, undefined);
    return undefined;
  };
  const mapped = (source) => {
    if (mappingCache.has(source)) return mappingCache.get(source);
    let mapping = null;
    for (const request of configRequests) {
      if (!request.dst || request.matching) continue;
      if (!spend(request.src, source)) return unknownMapping(source);
      const capture = patternCapture(request.src, source);
      if (capture !== null) {
        mapping = { destination: request.dst.replace('*', capture), force: request.force };
        break;
      }
    }
    // A negative preflight cannot change an already absent positive mapping.
    if (!mapping) { mappingCache.set(source, null); return null; }
    // Git's configured-query negative preflight reverses DST patterns into SRC
    // candidates, even for a source query. It is distinct from final PUSH exclusions.
    const reversed = new Set();
    for (const request of configRequests) {
      if (!spend(request.dst ?? request.src, request.src, source)) return unknownMapping(source);
      if (request.matching) reversed.add(source);
      else if (request.pattern) {
        const capture = patternCapture(request.dst ?? request.src, source);
        if (capture !== null) reversed.add(request.src.replace('*', capture));
      } else if (request.src === source) reversed.add(request.src);
    }
    for (const ref of reversed) {
      if (!spend(ref)) return unknownMapping(source);
      if (configNegativeNames.has(ref)) { mappingCache.set(source, null); return null; }
      for (const pattern of configNegativePatterns) {
        if (!spend(pattern, ref)) return unknownMapping(source);
        if (patternCapture(pattern, ref) !== null) { mappingCache.set(source, null); return null; }
      }
    }
    mappingCache.set(source, mapping);
    return mapping;
  };
  const normalize = (raw, caller) => {
    // --delete wraps a literal target; '+' in its name is not a force prefix.
    if (caller && options.remove) return { kind: 'delete', dst: raw, forced: false };
    const forced = raw.startsWith('+');
    const spec = forced ? raw.slice(1) : raw;
    if (spec.startsWith('^')) return { kind: 'negative' };
    if (spec === ':') return { kind: 'matching', forced };
    const colon = spec.indexOf(':');
    if (colon >= 0) return { kind: 'pair', src: spec.slice(0, colon), dst: spec.slice(colon + 1), forced };
    if (options.remove) return { kind: 'delete', dst: spec, forced };
    // Git expands a colonless source pattern into an identical destination pattern.
    if (spec.includes('*')) return { kind: 'pair', src: spec, dst: spec, forced };
    // Mapping uses the RAW token's unique canonical identity. A literal +name ref can
    // match; an ordinary unmatched force-prefix/HEAD operand resolves only afterward.
    const rawMatches = caller ? localMatches(raw) : [];
    if (rawMatches.length === 1) {
      const canonical = rawMatches[0];
      const mapping = mapped(canonical);
      if (mapping === undefined) return { kind: 'unknown' }; // no invented fallback
      if (mapping) return { kind: 'pair', src: canonical, dst: mapping.destination, forced: mapping.force };
      const sourceBranch = canonical.replace(/^refs\/heads\//, '');
      const upstream = values(`branch.${sourceBranch}.merge`);
      if (canonical.startsWith('refs/heads/') && upstream.length === 1
          && (mode === 'upstream' || mode === 'tracking')) {
        // Git rewrites this fallback from the original operand, which may carry '+'.
        const source = fullSource(spec);
        return source ? { kind: 'pair', src: source, dst: upstream[0], forced } : { kind: 'unknown', forced };
      }
    }
    // Configured defaults and unmapped caller operands resolve as raw refspecs.
    const source = fullSource(spec);
    if (!source) return { kind: 'unknown', forced };
    return { kind: 'pair', src: source, dst: source, forced };
  };
  const inspectPair = ({ src, dst, forced }) => {
    if (!dst) { unresolved = true; return; }
    if (dst.includes('*')) {
      if (!state.refsKnown) unresolved = true;
      // Invert over a fixed protected domain rather than scanning refs × refspecs.
      // Preserve each candidate's case until the active negative filter inside add().
      for (const ref of protectedRefs) {
        const capture = patternCapture(dst, ref);
        if (capture !== null && (refSet.has(src.replace('*', capture)) || options.prune)) {
          const selected = add(ref, forced);
          if (options.prune && selected) pruneDeletion = true;
        }
      }
      return;
    }
    // An unqualified tag-derived destination can select an existing remote branch or
    // become a tag on an empty remote. Local reads cannot establish that namespace.
    if (!dst.startsWith('refs/') && fullSource(src).startsWith('refs/tags/')) unresolved = true;
    else add(dst, forced);
  };
  const inspect = (raw, caller = false) => {
    const request = normalize(raw, caller);
    force ||= !!request.forced;
    if (request.kind === 'matching') matching(request.forced);
    else if (request.kind === 'delete') add(request.dst, request.forced);
    else if (request.kind === 'pair') inspectPair(request);
    else if (request.kind !== 'negative') unresolved = true;
  };
  if (options.all) matching();
  else if (options.refs.length) {
    for (let i = 0; i < options.refs.length; i += 1) {
      if (options.refs[i] === 'tag' && i + 1 < options.refs.length) { i += 1; continue; }
      inspect(options.refs[i], true);
    }
  } else if (!options.tags) {
    if (configured.length) for (const spec of configured) inspect(spec);
    else if (mode === 'matching') matching();
    else if (mode === 'nothing') { /* Git rejects an unspecified push; no destination selected. */ }
    else if (mode === 'upstream' || mode === 'tracking') {
      const upstream = values(`branch.${branch}.merge`);
      if (remote === branchRemote && upstream.length === 1) add(upstream[0]);
      else unresolved = true;
    } else if (branch) {
      const upstream = values(`branch.${branch}.merge`);
      if (mode !== 'simple' || remote !== branchRemote || !upstream.length || upstream[0] === currentRef) add(currentRef);
    } else unresolved = true;
  }
  return { targets: [...targets], force, mirror: false, prune: pruneDeletion, unresolved };
}

/**
 * Template identifiers, parsed and matched.
 *
 * A project instantiated from a pipeline template carries a `template_origin`
 * stamped by the CLI (`depictio/cli/cli/utils/templates.py`) whose
 * `template_id` looks like `nf-core/rnaseq/3.26.0`. Both listings — projects
 * directly, dashboards through their owning project — filter on it, and the
 * rules are subtle enough (version-agnostic matching, ids that omit segments)
 * to be worth keeping in one tested place.
 */

export interface ParsedTemplate {
  /** Original full identifier, e.g. `nf-core/viralrecon/3.0.0` */
  full: string;
  /** First slash-separated segment, e.g. `nf-core` */
  source: string;
  /** Middle segment if present, e.g. `viralrecon` */
  repo: string;
  /** Trailing segment if it looks like a semver, otherwise empty */
  version: string;
}

/** Parse a raw `template_origin` into source/repo/version. Accepts the
 *  object the API serves (`{template_id, template_version, ...}`) and a plain
 *  string, and tolerates ids that omit the version segment. Returns null when
 *  the project wasn't created from a template. */
export function parseTemplateOrigin(origin: unknown): ParsedTemplate | null {
  let raw: string | null = null;
  if (typeof origin === 'string') {
    raw = origin.trim();
  } else if (
    origin &&
    typeof origin === 'object' &&
    typeof (origin as { template_id?: unknown }).template_id === 'string'
  ) {
    raw = ((origin as { template_id: string }).template_id || '').trim();
  }
  if (!raw) return null;
  const parts = raw.split('/').map((s) => s.trim()).filter(Boolean);
  const looksVersion = (s: string) => /^v?\d/.test(s);
  let version = '';
  if (parts.length >= 2 && looksVersion(parts[parts.length - 1])) {
    version = parts.pop() || '';
  }
  const source = parts[0] || raw;
  const repo = parts[1] || '';
  return { full: raw, source, repo, version };
}

/** The canonical filter values a template offers: its source (`nf-core`)
 *  and, when the id names one, its pipeline (`nf-core/rnaseq`). These are the
 *  values a listing puts in its Template dropdown and writes into the URL.
 *
 *  The version is deliberately absent. Someone sharing "every rnaseq
 *  dashboard" means every version of rnaseq — pinning 3.26.0 into the link
 *  would silently drop the 3.27.0 project the day it lands. */
export function templateFilterValues(parsed: ParsedTemplate): string[] {
  const values = [parsed.source];
  if (parsed.repo) values.push(`${parsed.source}/${parsed.repo}`);
  return values;
}

/** Every spelling a template answers to when a filter value is matched
 *  against it: the canonical values above plus the bare pipeline name, so a
 *  hand-written `?template=rnaseq` works as well as the full id the Share
 *  button emits. */
function templateMatchKeys(parsed: ParsedTemplate): string[] {
  const keys = templateFilterValues(parsed);
  if (parsed.repo) keys.push(parsed.repo);
  return keys.map((k) => k.toLowerCase());
}

/** The one key a selected filter value stands for — its most specific
 *  segment. `nf-core` scopes to the whole source; `nf-core/rnaseq` (and
 *  `nf-core/rnaseq/3.26.0`, whose version is dropped on the way in) scopes to
 *  that pipeline alone. */
function selectionKey(selected: string): string | null {
  const parsed = parseTemplateOrigin(selected);
  if (!parsed) return null;
  const values = templateFilterValues(parsed);
  return values[values.length - 1].toLowerCase();
}

/** Does this template origin match any of the selected filter values?
 *
 *  Matching is case-insensitive and version-agnostic. An empty selection
 *  matches everything — "no filter", not "nothing" — while an origin that
 *  isn't from a template matches nothing once a selection exists. */
export function matchesTemplateFilter(origin: unknown, selected: string[]): boolean {
  if (selected.length === 0) return true;
  const parsed = parseTemplateOrigin(origin);
  if (!parsed) return false;
  const keys = new Set(templateMatchKeys(parsed));
  return selected.some((raw) => {
    const key = selectionKey(raw);
    return key != null && keys.has(key);
  });
}

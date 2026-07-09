/**
 * The build-generated snapshot of the *existing* catalog (public/catalog.json,
 * from `dev catalog manifest --json`). Powers two things the wizard needs to
 * compare itself against what's already in `depictio/catalog/`:
 *   - duplicate detection on the Tool step ("this tool already exists"), and
 *   - "add a visualization to an existing tool" (reuse its fixture + append a
 *     render to its output YAML).
 */
import { useEffect, useState } from 'react';
import { canonicalNfCoreUrl } from './fromNfCore';

/** One existing render in an output's `renders_as` (raw catalog dict). */
export interface ManifestRender {
  component: string;
  id?: string;
  kind?: string;
  visu_type?: string;
  [k: string]: unknown;
}

export interface ManifestOutput {
  id: string;
  slug: string;
  description?: string;
  path_glob?: string;
  columns?: Record<string, string>;
  renders_as: ManifestRender[];
  fixture?: string | null;
  /** A representative CSV/TSV sample (header + up to 200 rows), if co-located. */
  fixtureContent?: string | null;
  /** Repo-relative path of the output's YAML (for the append-a-render PR). */
  yamlPath?: string | null;
  /** The output YAML's raw text (append target). */
  rawYaml?: string | null;
}

export interface ManifestTool {
  id: string;
  name: string;
  description?: string;
  homepage?: string | null;
  nf_core_url?: string | null;
  biotools_url?: string | null;
  dir?: string | null;
  outputs: ManifestOutput[];
}

export interface CatalogManifest {
  tools: ManifestTool[];
}

const EMPTY: CatalogManifest = { tools: [] };

/** Load the committed catalog snapshot; empty (no duplicate/existing features)
 *  until loaded or if it's missing. */
export function useCatalog(): { catalog: CatalogManifest; loading: boolean } {
  const [catalog, setCatalog] = useState<CatalogManifest>(EMPTY);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}catalog.json`)
      .then((r) => r.json())
      .then((data: CatalogManifest) => {
        if (!cancelled && data && Array.isArray(data.tools)) setCatalog(data);
      })
      .catch(() => {
        /* leave empty — the wizard still works, just without cross-checks */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { catalog, loading };
}

const norm = (s: string | null | undefined) => (s ?? '').trim().toLowerCase();

/** Why a wizard tool matches an existing catalog tool (for the warning copy). */
export type DuplicateReason = 'id' | 'name' | 'nf-core module';

export interface DuplicateMatch {
  tool: ManifestTool;
  reason: DuplicateReason;
}

/** Find an existing catalog tool that the in-progress wizard tool collides with
 *  — by id, display name, or the same nf-core module path. */
export function findDuplicateTool(
  catalog: CatalogManifest,
  draft: { id?: string; name?: string; nf_core_url?: string | null },
): DuplicateMatch | null {
  const id = norm(draft.id);
  const name = norm(draft.name);
  const mod = draft.nf_core_url ? canonicalNfCoreUrl(draft.nf_core_url) : '';
  for (const tool of catalog.tools) {
    if (id && norm(tool.id) === id) return { tool, reason: 'id' };
    if (name && norm(tool.name) === name) return { tool, reason: 'name' };
    if (mod && tool.nf_core_url && canonicalNfCoreUrl(tool.nf_core_url) === mod)
      return { tool, reason: 'nf-core module' };
  }
  return null;
}

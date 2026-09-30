/**
 * Companion data collections of the protein kinds (molecule_3d, msa,
 * sequence_track): which DCs of the project each picker offers, and the
 * config patch a pick writes.
 *
 * The bound DC comes from the builder's data step; these are the extra
 * collections a kind reads beside it (the structure files, an alignment, the
 * domain spans, the variants). Each is stored as the `<base>_dc_id` /
 * `<base>_wf_id` pair of the config model. A template ships `<base>_dc_tag`
 * instead, which the import resolves; a pick in the builder names the ids, so
 * it drops the tag.
 */
import type { WorkflowEntry } from 'depictio-react-core';

export type CompanionBase = 'structure' | 'msa' | 'domains' | 'variants';

export interface CompanionOption {
  value: string;
  label: string;
  wfId: string;
}

/** Indexed-file formats that hold a protein structure (indexed_file.py). */
const STRUCTURE_FORMATS = new Set(['pdb', 'mmcif']);

type Dc = NonNullable<WorkflowEntry['data_collections']>[number];

function dcType(dc: Dc): string {
  return String(dc.config?.type ?? '').toLowerCase();
}

function dcFormat(dc: Dc): string {
  const props = dc.config?.dc_specific_properties as Record<string, unknown> | undefined;
  return String(props?.format ?? '').toLowerCase();
}

/** Whether a DC can serve `base`: structures are pdb/mmcif indexed files,
 *  the three others are ordinary tables. */
export function isCompanionCandidate(base: CompanionBase, dc: Dc): boolean {
  if (base === 'structure') return dcType(dc) === 'indexed_file' && STRUCTURE_FORMATS.has(dcFormat(dc));
  return dcType(dc) === 'table';
}

/** Picker options for `base` across the project's workflows. `excludeDcId`
 *  leaves out the tile's own bound DC (a table is never its own companion). */
export function companionOptions(
  workflows: readonly WorkflowEntry[],
  base: CompanionBase,
  excludeDcId?: string | null,
): CompanionOption[] {
  const multiWorkflow = workflows.length > 1;
  const out: CompanionOption[] = [];
  for (const wf of workflows) {
    for (const dc of wf.data_collections ?? []) {
      if (!dc._id || dc._id === excludeDcId || !isCompanionCandidate(base, dc)) continue;
      const tag = dc.data_collection_tag || dc._id;
      const wfName = wf.name || wf.workflow_tag || wf._id;
      out.push({
        value: dc._id,
        label: multiWorkflow ? `${tag} (${wfName})` : tag,
        wfId: wf._id,
      });
    }
  }
  return out;
}

/** The config patch for picking `dcId` (null clears) as `base`. `undefined`
 *  values tell the builder to drop the key. */
export function companionPatch(
  base: CompanionBase,
  dcId: string | null,
  options: readonly CompanionOption[],
): Record<string, unknown> {
  const opt = dcId ? options.find((o) => o.value === dcId) : undefined;
  return {
    [`${base}_dc_id`]: opt ? opt.value : undefined,
    [`${base}_wf_id`]: opt ? opt.wfId : undefined,
    [`${base}_dc_tag`]: undefined,
  };
}

/** Column names out of a `/deltatables/specs` payload (a list of `{name}` or
 *  a mapping keyed by column). */
export function specColumns(specs: unknown): string[] {
  if (Array.isArray(specs)) {
    return specs
      .map((s) => (s && typeof s === 'object' ? (s as { name?: unknown }).name : null))
      .filter((n): n is string => typeof n === 'string' && n.length > 0);
  }
  if (specs && typeof specs === 'object') return Object.keys(specs as Record<string, unknown>);
  return [];
}

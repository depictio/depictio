/**
 * Kinds whose required roles depend on a config field, not on the kind alone.
 *
 * The builder reads a kind's roles off the `/advanced_viz/kinds` descriptor, one
 * fixed set per kind. `hmm_logo` is the exception: with `profile_source: msa` it
 * computes the logo from an alignment table (the `msa` kind's schema) instead of
 * reading a parsed profile HMM, so the columns it asks for change with the
 * switch. This mirrors the mode-aware role hook on the Python side; the split
 * below is the only place the builder knows about it.
 */
import type { AdvancedVizKindDescriptor } from 'depictio-react-core';

/** `[role, accepted dtypes, description]`, the shape the binding table renders. */
export type RoleEntry = [string, string[], string];

export interface RoleSplit {
  required: RoleEntry[];
  optional: RoleEntry[];
}

/** The roles of `hmm_logo`'s alignment mode, which are the `msa` kind's own
 *  (`msa_id_col`, `seq_id_col`, `sequence_col`, `rank_col`). */
const HMM_LOGO_MSA_REQUIRED = ['msa_id', 'seq_id', 'sequence'] as const;
const HMM_LOGO_MSA_OPTIONAL = ['rank'] as const;
const HMM_LOGO_MSA_ROLES: ReadonlySet<string> = new Set([
  ...HMM_LOGO_MSA_REQUIRED,
  ...HMM_LOGO_MSA_OPTIONAL,
]);

/** The mode a kind's roles are read in, or null when its roles are fixed. */
export type RoleMode = 'msa';

export function roleModeOf(
  vizKind: string | null | undefined,
  config: Record<string, unknown> | null | undefined,
): RoleMode | null {
  return vizKind === 'hmm_logo' && config?.profile_source === 'msa' ? 'msa' : null;
}

const entryOf = (
  role: string,
  spec: { dtypes: string[]; description?: string },
): RoleEntry => [role, spec.dtypes, spec.description ?? ''];

/**
 * The required and optional roles of `descriptor` in `mode`.
 *
 * With no mode this is the descriptor as it stands, except that `hmm_logo`
 * hides the alignment roles (a descriptor may list them as optional so that the
 * bindings validate in either mode, but in profile mode they bind nothing).
 * In alignment mode the roles are the msa trio plus the optional rank. A role
 * the `hmm_logo` descriptor does not carry takes its dtypes from `msaDescriptor`
 * (the `msa` kind's), so the switch works whichever way the backend lists them.
 */
export function splitRoles(
  descriptor: AdvancedVizKindDescriptor | null | undefined,
  mode: RoleMode | null,
  msaDescriptor?: AdvancedVizKindDescriptor | null,
): RoleSplit {
  if (!descriptor) return { required: [], optional: [] };
  if (mode === 'msa') {
    const pick = (roles: readonly string[]): RoleEntry[] =>
      roles.flatMap((role) => {
        const spec = descriptor.roles[role] ?? msaDescriptor?.roles[role];
        return spec ? [entryOf(role, spec)] : [];
      });
    return { required: pick(HMM_LOGO_MSA_REQUIRED), optional: pick(HMM_LOGO_MSA_OPTIONAL) };
  }
  const hidden = descriptor.viz_kind === 'hmm_logo' ? HMM_LOGO_MSA_ROLES : null;
  const entries = Object.entries(descriptor.roles).filter(([role]) => !hidden?.has(role));
  return {
    required: entries.filter(([, spec]) => spec.required).map(([role, spec]) => entryOf(role, spec)),
    optional: entries.filter(([, spec]) => !spec.required).map(([role, spec]) => entryOf(role, spec)),
  };
}

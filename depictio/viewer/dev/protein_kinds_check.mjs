/**
 * The builder's side of the protein kinds: do its mirrors agree with the
 * renderers, and does the HMM logo's alignment mode ask for the right columns?
 *
 * `recordCardLink.ts` keeps its own copy of what `selection.ts` decides (which
 * kinds select by default, and on which column), because the package does not
 * export it. A copy drifts silently: a kind added to one and not the other
 * leaves the record-card picker offering a tile that never emits, or hiding one
 * that does. This compares the two for every protein kind.
 */

import { advancedVizSelectionColumn } from '../../../packages/depictio-react-core/src/selection';
import { roleModeOf, splitRoles } from '../src/builder/advanced_viz/kindModes';
import { isCompanionCandidate } from '../src/builder/advanced_viz/proteinBindings';
import { selectionEmitters } from '../src/builder/advanced_viz/recordCardLink';

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${JSON.stringify(got)}`);
  if (!ok) {
    console.log(`      want ${JSON.stringify(want)}`);
    failures++;
  }
}

const NEW_KINDS = ['hmm_logo', 'secondary_structure', 'domain_architecture', 'pae_matrix', 'ramachandran'];
const ALL_PROTEIN_KINDS = ['molecule_3d', 'msa', 'sequence_track', ...NEW_KINDS];

const tile = (viz_kind, config = {}) => ({
  index: `${viz_kind}-1`,
  component_type: 'advanced_viz',
  viz_kind,
  config,
});

console.log('1. The record-card picker agrees with the renderers');
for (const kind of ALL_PROTEIN_KINDS) {
  for (const config of [{}, { selection_enabled: false }, { position_col: 'resnum', label_col: 'family' }]) {
    const column = advancedVizSelectionColumn(tile(kind, config));
    const [emitter] = selectionEmitters([tile(kind, config)], null);
    check(
      `${kind} ${JSON.stringify(config)}`,
      emitter ? emitter.column : undefined,
      column,
    );
  }
}
for (const kind of NEW_KINDS) {
  const [emitter] = selectionEmitters([tile(kind)], null);
  check(`${kind} reaches a record card as a residue pick`, emitter?.source, 'residue_selection');
}
check(
  'domain_architecture names its label column',
  selectionEmitters([tile('domain_architecture', { label_col: 'family' })], null)[0]?.column,
  'family',
);

console.log('\n2. Companion collections');
const dc = (type, format) => ({
  _id: `${type}-${format ?? 'none'}`,
  config: { type, dc_specific_properties: format ? { format } : {} },
});
check('pae takes a pae indexed file', isCompanionCandidate('pae', dc('indexed_file', 'pae')), true);
check('pae refuses a structure file', isCompanionCandidate('pae', dc('indexed_file', 'pdb')), false);
check('pae refuses a table', isCompanionCandidate('pae', dc('table')), false);
check('structure still refuses a pae file', isCompanionCandidate('structure', dc('indexed_file', 'pae')), false);
check('structure still takes a pdb file', isCompanionCandidate('structure', dc('indexed_file', 'pdb')), true);
check('hits takes a table', isCompanionCandidate('hits', dc('table')), true);
check('hits refuses an indexed file', isCompanionCandidate('hits', dc('indexed_file', 'pae')), false);

console.log('\n3. hmm_logo asks for other columns in alignment mode');
const spec = (required, dtypes = ['String']) => ({ required, dtypes, description: '' });
const hmmRoles = {
  state: spec(true, ['Int64']),
  letter: spec(true),
  emission: spec(true, ['Float64']),
  entity: spec(false),
  position: spec(false, ['Int64']),
};
const msaRoles = { msa_id: spec(true), seq_id: spec(true), sequence: spec(true), rank: spec(false, ['Int64']) };
const names = (entries) => entries.map(([role]) => role);

// The backend may list the alignment roles on hmm_logo (as optional) or leave
// them to the msa kind; the split must come out the same either way.
const lean = { viz_kind: 'hmm_logo', roles: hmmRoles };
const wide = { viz_kind: 'hmm_logo', roles: { ...hmmRoles, ...Object.fromEntries(Object.entries(msaRoles).map(([k, v]) => [k, { ...v, required: false }])) } };
const msaKind = { viz_kind: 'msa', roles: msaRoles };

check('mode: default is the profile', roleModeOf('hmm_logo', {}), null);
check('mode: profile_source hmm', roleModeOf('hmm_logo', { profile_source: 'hmm' }), null);
check('mode: profile_source msa', roleModeOf('hmm_logo', { profile_source: 'msa' }), 'msa');
check('mode: another kind ignores it', roleModeOf('msa', { profile_source: 'msa' }), null);
check('mode: no config', roleModeOf('hmm_logo', null), null);

for (const [label, descriptor] of [['lean descriptor', lean], ['wide descriptor', wide]]) {
  const hmm = splitRoles(descriptor, null, msaKind);
  check(`${label}, profile: required`, names(hmm.required), ['state', 'letter', 'emission']);
  check(`${label}, profile: optional hides the alignment roles`, names(hmm.optional), ['entity', 'position']);
  const aln = splitRoles(descriptor, 'msa', msaKind);
  check(`${label}, alignment: required`, names(aln.required), ['msa_id', 'seq_id', 'sequence']);
  check(`${label}, alignment: optional`, names(aln.optional), ['rank']);
}
check(
  'alignment dtypes come from the msa kind when hmm_logo lacks the role',
  splitRoles(lean, 'msa', msaKind).optional[0]?.[1],
  ['Int64'],
);
check('alignment without an msa descriptor offers nothing it cannot type', names(splitRoles(lean, 'msa', null).required), []);
check('another kind is untouched', names(splitRoles(msaKind, null, msaKind).required), ['msa_id', 'seq_id', 'sequence']);
check('no descriptor', splitRoles(null, null), { required: [], optional: [] });

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);

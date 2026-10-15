/**
 * The builder's side of the protein kinds: do its mirrors agree with the
 * renderers, does the HMM logo's alignment mode ask for the right columns, and
 * does a column picked in a settings panel survive the save?
 *
 * `recordCardLink.ts` keeps its own copy of what `selection.ts` decides (which
 * kinds select by default, and on which column), because the package does not
 * export it. A copy drifts silently: a kind added to one and not the other
 * leaves the record-card picker offering a tile that never emits, or hiding one
 * that does. This compares the two for every protein kind.
 */

import { advancedVizSelectionColumn } from '../../../packages/depictio-react-core/src/selection';
import {
  buildAdvancedVizConfigBlob,
  isPanelColumn,
  mergedPresetConfig,
  panelColumnOfRole,
  patchOverrides,
  rolesFromConfigBlob,
} from '../src/builder/advanced_viz/configBlob';
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
check(
  'domain_architecture selection_column wins over its label column',
  selectionEmitters(
    [tile('domain_architecture', { label_col: 'family', selection_column: 'domain_id' })],
    null,
  )[0]?.column,
  'domain_id',
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

// The builder's store as AdvancedVizBuilder.tsx drives it, without React: a
// saved component opened for editing (or a new one), the role table's rows,
// the settings panels' writes, and what Save persists. `saved()` is also what
// the settings panels are handed to display.
function builder(kind, savedConfig = null, mapping = null) {
  const state = {
    column_mapping: mapping ?? rolesFromConfigBlob(kind, savedConfig),
    config: savedConfig,
    viz_overrides: null,
  };
  const api = {
    // buildMetadata.buildAdvancedViz and AdvancedVizPreview
    saved: () => buildAdvancedVizConfigBlob(kind, state.column_mapping, mergedPresetConfig(state)),
    mapping: () => state.column_mapping,
    // setOverrideFields: every settings panel's onChange
    panel: (patch) => {
      state.viz_overrides = patchOverrides(state.config, state.viz_overrides, patch);
    },
    // setRole: a role-table row; a panel-owned column goes to the panel's store
    role: (role, value) => {
      const key = panelColumnOfRole(kind, role);
      if (key) return api.panel({ [key]: typeof value === 'string' && value ? value : null });
      const next = { ...state.column_mapping };
      if (value == null) delete next[role];
      else next[role] = value;
      state.column_mapping = next;
    },
  };
  return api;
}

console.log('\n4. A column picked in a settings panel is the one saved');
const savedHmm = {
  viz_kind: 'hmm_logo',
  state_col: 'hmm_position',
  letter_col: 'hmm_letter',
  emission_col: 'emission',
  hits_dc_id: 'hits-dc',
  hits_wf_id: 'wf',
  hits_model_col: 'label',
  hits_evalue_col: 'i_evalue',
  max_hits: 50,
};
check(
  'hmm_logo: an edited logo recovers its roles, not its hits columns',
  rolesFromConfigBlob('hmm_logo', savedHmm),
  { state: 'hmm_position', letter: 'hmm_letter', emission: 'emission' },
);
let b = builder('hmm_logo', savedHmm);
check('hmm_logo: untouched, the saved hits model column stays', b.saved().hits_model_col, 'label');
b.panel({ hits_model_col: 'family' });
check('hmm_logo: the Model picker changed to family is saved as family', b.saved().hits_model_col, 'family');
check('hmm_logo: the other hits columns and limits ride along', [b.saved().hits_evalue_col, b.saved().hits_dc_id, b.saved().max_hits], ['i_evalue', 'hits-dc', 50]);
check('hmm_logo: the roles are still the mapping\'s', b.saved().state_col, 'hmm_position');
b = builder('hmm_logo', savedHmm, { ...rolesFromConfigBlob('hmm_logo', savedHmm), hits_model: 'label' });
b.panel({ hits_model_col: 'family' });
check('hmm_logo: a stray hits_model role (catalog roles) does not outrank the panel', b.saved().hits_model_col, 'family');

const savedSs = {
  viz_kind: 'secondary_structure',
  position_col: 'position',
  state_col: 'ss_code',
  p_helix_col: 'p_helix',
  p_strand_col: 'p_strand',
};
b = builder('secondary_structure', savedSs);
check('secondary_structure: the panel-owned columns are not recovered as roles', b.mapping(), { position: 'position', state: 'ss_code' });
b.panel({ p_helix_col: null });
check('secondary_structure: P(helix) cleared in the panel is saved unbound', b.saved().p_helix_col, null);
check('secondary_structure: the untouched P(strand) stays', b.saved().p_strand_col, 'p_strand');
b = builder('secondary_structure', savedSs, { position: 'position', state: 'ss_code', p_helix: 'p_helix' });
b.panel({ p_helix_col: null });
check('secondary_structure: even over a p_helix role left in the mapping', b.saved().p_helix_col, null);

b = builder('secondary_structure', null, { position: 'position', state: 'ss_code' });
b.role('source', 'method');
check('secondary_structure: source bound in the role table is in what the panel reads', b.saved().source_col, 'method');
check('secondary_structure: ... and written once, in the panel\'s store', b.mapping().source, undefined);
b.panel({ reference_source: 's4pred' });
check('secondary_structure: the reference source can then be picked', b.saved().reference_source, 's4pred');
b.panel({ p_coil_col: 'coil' });
b.role('p_coil', 'coil2');
check('secondary_structure: the role row and the panel picker edit one key', b.saved().p_coil_col, 'coil2');
b.role('source', null);
check(
  'secondary_structure: unbinding the source in the role table drops the reference with it',
  [b.saved().source_col, 'reference_source' in b.saved()],
  [null, false],
);
b.role('state', 'dssp');
check('secondary_structure: state is still an ordinary binding', [b.mapping().state, b.saved().state_col], ['dssp', 'dssp']);
check('secondary_structure: the panel-owned roles', ['source', 'p_helix', 'p_strand', 'p_coil', 'confidence', 'state', 'position', 'residue', 'entity'].filter((r) => panelColumnOfRole('secondary_structure', r)), ['source', 'p_helix', 'p_strand', 'p_coil', 'confidence']);
b = builder('secondary_structure', null, { position: 'position', state: 'ss_code', source: 'method' });
check('secondary_structure: a source role from the catalog still reaches the config', b.saved().source_col, 'method');

const savedTrack = {
  viz_kind: 'sequence_track',
  position_col: 'position',
  residue_col: 'residue',
  domains_dc_id: 'dom-dc',
  domains_wf_id: 'wf',
  domain_label_col: 'label',
  variants_dc_id: 'var-dc',
  variant_category_col: 'category',
};
check('sequence_track: domains and variants columns are not roles', rolesFromConfigBlob('sequence_track', savedTrack), { position: 'position', residue: 'residue' });
b = builder('sequence_track', savedTrack);
b.panel({ domain_label_col: 'family', variant_category_col: 'consequence' });
check(
  'sequence_track: the domain and variant pickers are saved',
  [b.saved().domain_label_col, b.saved().variant_category_col, b.saved().domains_dc_id, b.saved().variants_dc_id],
  ['family', 'consequence', 'dom-dc', 'var-dc'],
);

const savedMol = {
  viz_kind: 'molecule_3d',
  position_col: 'position',
  value_col: 'plddt',
  structure_dc_id: 'pdb-dc',
  structure_wf_id: 'wf',
  layout: 'structure_msa',
  msa_dc_id: 'msa-dc',
  taxon: 10090,
};
b = builder('molecule_3d', savedMol);
b.role('value', 'score');
check(
  'molecule_3d: a role edit wins, the structure and alignment companions ride along',
  [b.saved().value_col, b.saved().structure_dc_id, b.saved().msa_dc_id, b.saved().taxon],
  ['score', 'pdb-dc', 'msa-dc', 10090],
);
b.panel({ msa_dc_id: undefined, msa_wf_id: undefined, layout: 'structure' });
check('molecule_3d: clearing the alignment nulls the saved one', [b.saved().msa_dc_id, b.saved().layout], [null, 'structure']);

b = builder('pae_matrix', { viz_kind: 'pae_matrix', position_col: 'position', value_col: 'plddt', pae_dc_id: 'pae-dc' });
b.role('value', 'confidence'); // PaeMatrixSettings' pLDDT picker writes the role
check('pae_matrix: the pLDDT picker (a role) beats the saved column', [b.saved().value_col, b.saved().pae_dc_id], ['confidence', 'pae-dc']);

b = builder('ramachandran', null, { position: 'position' });
b.role('category', 'domain');
check('ramachandran: a category bound in the role table enables its colour mode', b.saved().category_col, 'domain');

b = builder('domain_architecture', { viz_kind: 'domain_architecture', entity_col: 'entity', start_col: 'start', end_col: 'end', label_col: 'label', source_col: 'source' });
check('domain_architecture: its source column is a role', b.mapping().source, 'source');
b.role('source', 'database');
check('domain_architecture: and the mapping edits it', b.saved().source_col, 'database');

console.log('\n5. Clearing a field');
check('a cleared field the saved config had is nulled', patchOverrides({ marker_size: 8 }, null, { marker_size: undefined }), { marker_size: null });
check('a cleared field the saved config never had is dropped', patchOverrides({}, { marker_size: 8 }, { marker_size: undefined }), {});
check('a default written back stays a value', patchOverrides({ marker_size: 8 }, null, { marker_size: 6 }), { marker_size: 6 });

console.log('\n6. Other kinds keep their layering');
const savedVolcano = {
  viz_kind: 'volcano',
  feature_id_col: 'gene',
  effect_size_col: 'lfc',
  significance_col: 'padj',
  label_col: 'symbol',
  score_threshold: 2,
};
check(
  'volcano: every _col key is a role',
  rolesFromConfigBlob('volcano', savedVolcano),
  { feature_id: 'gene', effect_size: 'lfc', significance: 'padj', label: 'symbol' },
);
b = builder('volcano', savedVolcano);
b.role('label', 'name');
check('volcano: a role edit wins over the saved column', b.saved().label_col, 'name');
check('volcano: a viz control rides along', b.saved().score_threshold, 2);
check('dot_plot: source_col is a binding there', rolesFromConfigBlob('dot_plot', { source_col: 'db' }), { source: 'db' });
b = builder('dot_plot', { viz_kind: 'dot_plot', source_col: 'db' });
b.role('source', 'library');
check('dot_plot: and the mapping edits it', b.saved().source_col, 'library');
check('a panel column is scoped to its kind', [isPanelColumn('secondary_structure', 'source_col'), isPanelColumn('dot_plot', 'source_col'), isPanelColumn('constructor', 'source_col')], [true, false, false]);
const sunburst = buildAdvancedVizConfigBlob('sunburst', { abundance: 'n', ranks: ['k', 'p'] }, { rank_cols: ['x', 'y'], top_n: 5 });
check('sunburst: rank_cols travels as the ranks role', [sunburst.rank_cols, sunburst.abundance_col, sunburst.top_n], [['k', 'p'], 'n', 5]);
check(
  'complex_heatmap: index travels as index_column',
  rolesFromConfigBlob('complex_heatmap', { index_column: 'sample' }),
  { index: 'sample' },
);
check('coverage_track: a default view mode', buildAdvancedVizConfigBlob('coverage_track', { position: 'pos' }).view_mode, 'overlay');

// A structure tile bound to a sequence and to no structure collection resolves its structure.
check(
  'structure: a sequence binding resolves',
  buildAdvancedVizConfigBlob('molecule_3d', { sequence: 'sequence' }).structure_source,
  'resolve',
);
check(
  'structure: a bound collection keeps file mode',
  buildAdvancedVizConfigBlob('molecule_3d', { sequence: 'sequence' }, { structure_dc_tag: 'models' })
    .structure_source,
  undefined,
);
check(
  'structure: nothing to resolve from stays on the default',
  buildAdvancedVizConfigBlob('molecule_3d', {}).structure_source,
  undefined,
);
check(
  'structure: a stated file source is kept',
  buildAdvancedVizConfigBlob('molecule_3d', { gene: 'gene' }, { structure_source: 'file' })
    .structure_source,
  'file',
);
check(
  'structure: another kind is untouched',
  buildAdvancedVizConfigBlob('lollipop', { sequence: 'sequence' }).structure_source,
  undefined,
);

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);

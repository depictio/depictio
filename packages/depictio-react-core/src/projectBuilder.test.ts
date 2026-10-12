import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  builderCapabilities,
  builderMatch,
  builderTemplate,
  builderTracksManifest,
  builderTree,
  builderWriteManifest,
  createProjectFromRun,
  previewRunFile,
} from './api';
import type { BuilderCapabilities } from './api';
import {
  BUILDER_HANDOFF_KEY,
  blockingIssues,
  builderDraftKey,
  builderReducer,
  clearBuilderDraft,
  coordinatesIssue,
  dcTypeAvailability,
  defaultDcProps,
  fallbackBuilderCapabilities,
  globToRegex,
  initialBuilderState,
  isTagTaken,
  loadBuilderDraft,
  linkIssues,
  newLinkDraft,
  normalizeDcDraft,
  offeredDcTypes,
  parseBuilderState,
  regexToGlob,
  saveBuilderDraft,
  seedPropsForCapabilities,
  tableTags,
  tagFromPath,
  takeBuilderHandoff,
  toProjectDraft,
  uniqueTag,
  validateBuilderState,
  wildcardIssues,
  writeBuilderHandoff,
} from './projectBuilder';
import type { BuilderDcDraft, BuilderState, BuilderStorage, BuilderTableProps } from './projectBuilder';

function table(tag: string, path = `${tag}.csv`): BuilderDcDraft {
  return { tag, type: 'table', mode: 'single', path, props: defaultDcProps('table', { path }) };
}

function memoryStorage(): BuilderStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => {
      data.set(k, v);
    },
    removeItem: (k) => {
      data.delete(k);
    },
  };
}

/** A project with one `main` workflow holding `tags` as table collections. */
function withTables(...tags: string[]): BuilderState {
  let state = initialBuilderState();
  for (const tag of tags) {
    state = builderReducer(state, { type: 'dc/save', workflowId: 'wf-0', dc: table(tag) });
  }
  return state;
}

describe('initial state', () => {
  it('starts with one main workflow, selected', () => {
    const state = initialBuilderState();
    expect(state.workflows).toHaveLength(1);
    expect(state.workflows[0]).toMatchObject({ name: 'main', engine: 'python', structure: 'flat' });
    expect(state.activeWorkflowId).toBe(state.workflows[0].id);
  });
});

describe('workflows', () => {
  it('adds workflows under unique names and selects the new one', () => {
    let state = initialBuilderState();
    state = builderReducer(state, { type: 'workflow/add' });
    state = builderReducer(state, { type: 'workflow/add', name: 'main' });
    expect(state.workflows.map((w) => w.name)).toEqual(['main', 'workflow_2', 'main_2']);
    expect(new Set(state.workflows.map((w) => w.id)).size).toBe(3);
    expect(state.activeWorkflowId).toBe(state.workflows[2].id);
  });

  it('never removes the last workflow', () => {
    const state = initialBuilderState();
    expect(builderReducer(state, { type: 'workflow/remove', id: 'wf-0' })).toBe(state);
  });

  it('moves the selection off a removed workflow and forgets its claims', () => {
    let state = builderReducer(initialBuilderState(), { type: 'workflow/add' });
    const second = state.activeWorkflowId;
    state = builderReducer(state, { type: 'dc/save', workflowId: second, dc: table('counts') });
    state = builderReducer(state, { type: 'workflow/remove', id: second });
    expect(state.workflows).toHaveLength(1);
    expect(state.activeWorkflowId).toBe('wf-0');
    expect(state.claimed.counts).toBeUndefined();
  });

  it('defaults the runs regex when switching to sequencing runs, and drops it back on flat', () => {
    let state = builderReducer(initialBuilderState(), {
      type: 'workflow/patch',
      id: 'wf-0',
      patch: { structure: 'sequencing-runs' },
    });
    expect(state.workflows[0].runs_regex).toBe('run_.*');
    state = builderReducer(state, { type: 'workflow/patch', id: 'wf-0', patch: { structure: 'flat' } });
    expect(state.workflows[0].runs_regex).toBeNull();
  });
});

describe('data collections', () => {
  it('refuses a tag another collection uses, anywhere in the project', () => {
    let state = withTables('counts');
    state = builderReducer(state, { type: 'workflow/add' });
    const other = state.activeWorkflowId;
    const next = builderReducer(state, { type: 'dc/save', workflowId: other, dc: table(' counts ') });
    expect(next).toBe(state);
    expect(isTagTaken(state, 'counts')).toBe(true);
    expect(isTagTaken(state, 'counts', 'counts')).toBe(false);
  });

  it('edits a collection in place, keeping its position', () => {
    let state = withTables('a', 'b', 'c');
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: { ...table('b'), tag: 'bee', description: 'renamed' },
      originalTag: 'b',
    });
    expect(state.workflows[0].data_collections.map((d) => d.tag)).toEqual(['a', 'bee', 'c']);
    expect(state.claimed.bee).toEqual(['b.csv']);
    expect(state.claimed.b).toBeUndefined();
  });

  it('moves a collection to another workflow when saved there', () => {
    let state = withTables('a', 'b');
    state = builderReducer(state, { type: 'workflow/add' });
    const second = state.activeWorkflowId;
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: second,
      dc: table('a'),
      originalTag: 'a',
    });
    expect(state.workflows[0].data_collections.map((d) => d.tag)).toEqual(['b']);
    expect(state.workflows[1].data_collections.map((d) => d.tag)).toEqual(['a']);
  });

  it('moves and removes collections', () => {
    let state = withTables('a', 'b');
    state = builderReducer(state, { type: 'workflow/add' });
    const second = state.activeWorkflowId;
    state = builderReducer(state, { type: 'dc/move', tag: 'b', workflowId: second });
    expect(state.workflows[1].data_collections.map((d) => d.tag)).toEqual(['b']);
    state = builderReducer(state, { type: 'dc/remove', tag: 'b' });
    expect(state.workflows[1].data_collections).toEqual([]);
    expect(state.claimed.b).toBeUndefined();
  });

  it('keeps the matched files for the file tree', () => {
    const state = builderReducer(initialBuilderState(), {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: { tag: 'quant', type: 'table', mode: 'recursive', regex: 'quant\\.sf$', props: defaultDcProps('table') },
      files: ['s1/quant.sf', 's2/quant.sf'],
    });
    expect(state.claimed.quant).toEqual(['s1/quant.sf', 's2/quant.sf']);
  });

  it('points a phylogeny at a renamed metadata table', () => {
    let state = withTables('samples');
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: {
        tag: 'tree',
        type: 'phylogeny',
        mode: 'single',
        path: 'tree.nwk',
        props: { kind: 'phylogeny', format: 'newick', metadata_dc_tag: 'samples' },
      },
    });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: table('metadata', 'samples.csv'),
      originalTag: 'samples',
    });
    const tree = state.workflows[0].data_collections.find((d) => d.tag === 'tree');
    expect(tree?.props).toMatchObject({ metadata_dc_tag: 'metadata' });
    expect(tableTags(state)).toEqual(['metadata']);
  });

  it('suggests free tags from file names', () => {
    const state = withTables('sample_counts');
    expect(tagFromPath('results/Sample-Counts.tsv.gz')).toBe('sample_counts');
    expect(uniqueTag(state, 'sample_counts')).toBe('sample_counts_2');
    expect(uniqueTag(state, 'sample_counts', 'sample_counts')).toBe('sample_counts');
  });
});

describe('validation', () => {
  it('asks for a project name and a collection', () => {
    const codes = validateBuilderState(initialBuilderState()).map((i) => i.code);
    expect(codes).toContain('project_name');
    expect(codes).toContain('no_collections');
    expect(codes).toContain('workflow_empty');
  });

  it('flags duplicate workflow names and a missing runs regex', () => {
    let state = withTables('a');
    state = builderReducer(state, { type: 'workflow/add' });
    const second = state.activeWorkflowId;
    state = builderReducer(state, { type: 'dc/save', workflowId: second, dc: table('b') });
    state = builderReducer(state, { type: 'workflow/patch', id: second, patch: { name: 'main' } });
    state = builderReducer(state, {
      type: 'workflow/patch',
      id: second,
      patch: { structure: 'sequencing-runs' },
    });
    state = builderReducer(state, { type: 'workflow/patch', id: second, patch: { runs_regex: ' ' } });
    const codes = validateBuilderState(state).map((i) => i.code);
    expect(codes.filter((c) => c === 'workflow_name_duplicate')).toHaveLength(2);
    expect(codes).toContain('runs_regex_missing');
  });

  it('requires a phylogeny metadata table to exist and be a table', () => {
    let state = withTables('samples');
    state = builderReducer(state, { type: 'project/patch', patch: { name: 'P' } });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: {
        tag: 'tree',
        type: 'phylogeny',
        mode: 'single',
        path: 'tree.nwk',
        props: { kind: 'phylogeny', format: 'newick', metadata_dc_tag: 'gone' },
      },
    });
    expect(validateBuilderState(state).map((i) => i.code)).toEqual(['phylogeny_metadata_missing']);
  });

  it('refuses indexed files on an s3 root only', () => {
    let state = builderReducer(initialBuilderState(), { type: 'project/patch', patch: { name: 'P' } });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: { tag: 'vcf', type: 'indexed_file', mode: 'single', path: 'a.vcf.gz', props: defaultDcProps('indexed_file', { path: 'a.vcf.gz' }) },
    });
    expect(validateBuilderState(state, { remote: false })).toEqual([]);
    expect(validateBuilderState(state, { remote: true }).map((i) => i.code)).toEqual([
      'indexed_file_remote',
    ]);
  });

  it('refuses images on an s3 root only', () => {
    let state = builderReducer(initialBuilderState(), { type: 'project/patch', patch: { name: 'P' } });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: {
        tag: 'cells',
        type: 'image',
        mode: 'single',
        path: 'cells.csv',
        props: { kind: 'image', format: 'csv', image_column: 'path' },
      },
    });
    expect(validateBuilderState(state, { remote: false })).toEqual([]);
    expect(validateBuilderState(state, { remote: true }).map((i) => i.code)).toEqual(['image_remote']);
  });

  it('refuses a scan for a type that reads one file', () => {
    let state = builderReducer(initialBuilderState(), { type: 'project/patch', patch: { name: 'P' } });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: {
        tag: 'tree',
        type: 'phylogeny',
        mode: 'recursive',
        regex: '^tree\\.nwk$',
        props: { kind: 'phylogeny', format: 'newick' },
      },
    });
    expect(validateBuilderState(state).map((i) => i.code)).toEqual(['single_file_type_scanned']);
  });
});

describe('what is sent', () => {
  it('strips page-only fields and the fields a mode does not use', () => {
    let state = builderReducer(initialBuilderState(), {
      type: 'project/patch',
      patch: { name: ' Survey ', description: '  ', realtime: true },
    });
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: {
        tag: 'quant',
        type: 'table',
        mode: 'recursive',
        path: 'stale.csv',
        glob: '*.sf',
        regex: '.*\\.sf$',
        max_depth: 2,
        ignore: ['work', ' '],
        props: { kind: 'table', format: 'tsv', separator: '\t', columns_description: { a: 'x', b: ' ' } },
      },
    });
    state = builderReducer(state, {
      type: 'workflow/patch',
      id: 'wf-0',
      patch: { meta: { repository_url: 'https://x', sources: [] }, repository_url: ' ' },
    });
    const draft = toProjectDraft(state);
    expect(draft).toEqual({
      name: 'Survey',
      realtime: true,
      workflows: [
        {
          name: 'main',
          engine: 'python',
          structure: 'flat',
          data_collections: [
            {
              tag: 'quant',
              type: 'table',
              mode: 'recursive',
              glob: '*.sf',
              regex: '.*\\.sf$',
              max_depth: 2,
              ignore: ['work'],
              props: { kind: 'table', format: 'tsv', separator: '\t', columns_description: { a: 'x' } },
            },
          ],
        },
      ],
    });
    const remote = toProjectDraft(state, { remote: true });
    expect(remote.workflows[0].data_collections[0]).not.toHaveProperty('max_depth');
    expect(remote.workflows[0].data_collections[0]).not.toHaveProperty('ignore');
  });

  it('replaces properties that belong to another type', () => {
    const dc = normalizeDcDraft({ ...table('t'), type: 'multiqc' });
    expect(dc.props).toEqual({ kind: 'multiqc' });
  });
});

describe('glob and regex', () => {
  it('turns a file-name glob into a re.match regex', () => {
    expect(globToRegex('*_counts.tsv')).toBe('.*_counts\\.tsv$');
    expect(globToRegex('**/*.parquet')).toBe('.*\\.parquet$');
    expect(globToRegex('sample_?.{csv,tsv}')).toBe('sample_.\\.(?:csv|tsv)$');
    expect(globToRegex('[!.]*.txt')).toBe('[^.].*\\.txt$');
  });

  it('keeps folders in a path glob, with * stopping at /', () => {
    expect(globToRegex('results/*/quant.sf')).toBe('results/[^/]*/quant\\.sf$');
    expect(globToRegex('results/**/quant.sf')).toBe('results/(?:.*/)?quant\\.sf$');
  });

  it('reads simple regexes back as globs', () => {
    for (const glob of ['*_counts.tsv', 'results/*/quant.sf', 'sample_?.{csv,tsv}', 'results/**/quant.sf']) {
      expect(regexToGlob(globToRegex(glob))).toBe(glob);
    }
    expect(regexToGlob('^sample_\\d\\.csv$')).toBe('sample_[0-9].csv');
    expect(regexToGlob('counts\\.tsv')).toBe('counts.tsv*');
  });

  it('gives up on regexes a glob cannot say', () => {
    expect(regexToGlob('sample_\\d+\\.csv$')).toBeNull();
    expect(regexToGlob('(?P<sample>[^_]+)_R1\\.fastq$')).toBeNull();
    expect(regexToGlob('a+b$')).toBeNull();
    expect(regexToGlob('')).toBeNull();
  });
});

describe('draft persistence', () => {
  it('saves and loads per data root', () => {
    const storage = memoryStorage();
    const state = withTables('a');
    saveBuilderDraft('/data/run1', state, storage);
    expect(storage.data.has(builderDraftKey('/data/run1'))).toBe(true);
    expect(loadBuilderDraft('/data/run1', storage)).toEqual(state);
    expect(loadBuilderDraft('/data/run2', storage)).toBeNull();
    clearBuilderDraft('/data/run1', storage);
    expect(loadBuilderDraft('/data/run1', storage)).toBeNull();
  });

  it('survives storage that throws or holds junk', () => {
    const throwing: BuilderStorage = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('quota');
      },
      removeItem: () => {
        throw new Error('denied');
      },
    };
    expect(() => saveBuilderDraft('/d', initialBuilderState(), throwing)).not.toThrow();
    expect(loadBuilderDraft('/d', throwing)).toBeNull();
    const junk = memoryStorage();
    junk.setItem(builderDraftKey('/d'), '{not json');
    expect(loadBuilderDraft('/d', junk)).toBeNull();
    expect(loadBuilderDraft('/d', null)).toBeNull();
  });

  it('rejects drafts that do not hold together and repairs what it can', () => {
    expect(parseBuilderState({ version: 1, workflows: [] })).toBeNull();
    expect(parseBuilderState({ version: 2 })).toBeNull();
    const repaired = parseBuilderState({
      version: 1,
      project: { name: 'P' },
      workflows: [
        { id: 'wf-4', name: 'main', data_collections: [{ tag: 't', type: 'table', mode: 'single', path: 'a.tsv' }] },
      ],
      activeWorkflowId: 'nope',
    });
    expect(repaired?.activeWorkflowId).toBe('wf-4');
    expect(repaired?.nextId).toBe(5);
    expect(repaired?.workflows[0].data_collections[0].props).toEqual({
      kind: 'table',
      format: 'tsv',
      separator: '\t',
    });
  });
});

describe('hand-off from the run-folder wizard', () => {
  it('is read once, then gone', () => {
    const storage = memoryStorage();
    expect(writeBuilderHandoff({ dataRoot: 's3://b/run', storage: null }, storage)).toBe(true);
    expect(takeBuilderHandoff(storage)).toEqual({ dataRoot: 's3://b/run', storage: null });
    expect(storage.data.has(BUILDER_HANDOFF_KEY)).toBe(false);
    expect(takeBuilderHandoff(storage)).toBeNull();
  });
});

describe('builder calls', () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];

  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const body = (i = 0) => JSON.parse(String(calls[i].init.body));

  it('posts to the builder routes, the storage only when there is some', async () => {
    await builderTree({ data_root: '/d', storage: null }, 'sub');
    expect(calls[0].url).toBe('/depictio/api/v1/projects/builder/tree');
    expect(body()).toEqual({ root: { data_root: '/d' }, path: 'sub' });

    await builderMatch(
      { data_root: '/d' },
      { structure: 'flat', runs_regex: 'ignored' },
      table('t'),
    );
    expect(body(1).workflow).toEqual({ structure: 'flat' });

    await builderTemplate({ name: 'P', workflows: [] }, true);
    expect(body(2)).toEqual({ draft: { name: 'P', workflows: [] }, remote: true });
  });

  it('sends an inline template to from_run instead of a template id', async () => {
    await createProjectFromRun({ dataRoot: '/d', template: { a: 1 }, dryRun: true });
    expect(body()).toMatchObject({ data_root: '/d', template: { a: 1 }, dry_run: true });
    expect(body()).not.toHaveProperty('template_id');
    await createProjectFromRun({ dataRoot: '/d', templateId: 'nf-core/x/1.0.0' });
    expect(body(1)).toMatchObject({ template_id: 'nf-core/x/1.0.0' });
    expect(body(1)).not.toHaveProperty('template');
  });

  it('asks the file preview for dtypes only when told to', async () => {
    await previewRunFile({ dataRoot: '/d', location: '/d/a.csv' });
    expect(body()).not.toHaveProperty('infer_types');
    await previewRunFile({ dataRoot: '/d', location: '/d/a.csv', inferTypes: true });
    expect(body(1).infer_types).toBe(true);
  });
});

// ── Contract v2 ─────────────────────────────────────────────────────────────

/** What a v2 server answers before the genomic tracks and bioimage kinds
 *  land: every core type, the two new ones unavailable with a reason. */
function capabilities(overrides: Partial<BuilderCapabilities> = {}): BuilderCapabilities {
  return {
    mode: 'server',
    dc_types: [
      ...fallbackBuilderCapabilities().dc_types,
      { type: 'genomic_tracks', available: false, reason: 'Genomic tracks need the genome browser extension.' },
      { type: 'bioimage', available: false, reason: 'Bioimages need the bioimage extension.' },
    ],
    table_formats: ['csv', 'tsv', 'parquet', 'feather', 'xls', 'xlsx'],
    reader_options: [
      'separator',
      'has_header',
      'skip_rows',
      'comment_prefix',
      'null_values',
      'quote_char',
      'decimal_comma',
    ],
    link_target_types: ['table', 'multiqc', 'image'],
    realtime: { events_enabled: true, reason: null },
    genomic_tracks: null,
    bioimage: null,
    ...overrides,
  };
}

/** Every type available, as a server with both extensions answers. */
function fullCapabilities(): BuilderCapabilities {
  const base = capabilities();
  return {
    ...base,
    dc_types: base.dc_types.map((t) => ({ ...t, available: true, reason: null })),
    table_formats: [...base.table_formats, 'spatialdata'],
    link_target_types: ['table', 'multiqc', 'image', 'genomic_tracks'],
    genomic_tracks: { assemblies: ['hg38', 'mm10'], track_formats: ['bigwig', 'bam', 'vcf'] },
    bioimage: { formats: ['ome-zarr', 'ome-tiff', 'spatialdata'] },
  };
}

type Props = BuilderDcDraft['props'];

function tracks(tag: string, extra: Partial<BuilderDcDraft> = {}): BuilderDcDraft {
  const props = defaultDcProps('genomic_tracks', { path: 'tracks/manifest.tsv' });
  return {
    tag,
    type: 'genomic_tracks',
    mode: 'single',
    path: 'tracks/manifest.tsv',
    props: { ...props, assembly: 'hg38' } as Props,
    ...extra,
  };
}

function save(state: BuilderState, dc: BuilderDcDraft): BuilderState {
  return builderReducer(state, { type: 'dc/save', workflowId: 'wf-0', dc });
}

function named(state: BuilderState): BuilderState {
  return builderReducer(state, { type: 'project/patch', patch: { name: 'P' } });
}

const errorCodes = (state: BuilderState, options: Parameters<typeof validateBuilderState>[1] = {}) =>
  blockingIssues(validateBuilderState(state, options)).map((i) => i.code);

describe('capabilities gating', () => {
  it('offers the core six types until the server says more', () => {
    expect(offeredDcTypes(fallbackBuilderCapabilities())).toEqual([
      'table',
      'multiqc',
      'image',
      'indexed_file',
      'geojson',
      'phylogeny',
    ]);
    expect(offeredDcTypes(capabilities())).toContain('genomic_tracks');
    expect(dcTypeAvailability('genomic_tracks', capabilities())).toEqual({
      type: 'genomic_tracks',
      available: false,
      reason: 'Genomic tracks need the genome browser extension.',
    });
    expect(dcTypeAvailability('bioimage', fallbackBuilderCapabilities()).available).toBe(false);
  });

  it('never sends a collection of a type the server does not build', () => {
    const state = named(save(withTables('samples'), tracks('coverage')));
    const caps = capabilities();
    expect(validateBuilderState(state, { capabilities: caps })).toContainEqual(
      expect.objectContaining({
        level: 'error',
        code: 'dc_type_unavailable',
        tag: 'coverage',
        message: '“coverage”: Genomic tracks need the genome browser extension.',
      }),
    );
    const draft = toProjectDraft(state, { capabilities: caps });
    expect(draft.workflows.flatMap((w) => w.data_collections.map((dc) => dc.type))).toEqual(['table']);
    // Once the server builds it, it goes.
    const full = fullCapabilities();
    expect(errorCodes(state, { capabilities: full })).toEqual([]);
    expect(toProjectDraft(state, { capabilities: full }).workflows[0].data_collections).toHaveLength(2);
  });

  it('drops realtime when the server has real-time events off', () => {
    const state = builderReducer(named(withTables('a')), { type: 'project/patch', patch: { realtime: true } });
    expect(toProjectDraft(state, { capabilities: capabilities() }).realtime).toBe(true);
    const off = capabilities({ realtime: { events_enabled: false, reason: 'off' } });
    expect(toProjectDraft(state, { capabilities: off })).not.toHaveProperty('realtime');
    // Unknown (standalone): kept, it takes effect on a server that has them.
    const unknown = capabilities({ mode: 'standalone', realtime: { events_enabled: null, reason: null } });
    expect(toProjectDraft(state, { capabilities: unknown }).realtime).toBe(true);
  });

  it('starts a genomic assembly at hg38 when the server lists no presets', () => {
    const props = defaultDcProps('genomic_tracks');
    const standalone = { ...fullCapabilities(), genomic_tracks: { assemblies: [], track_formats: [] } };
    expect(seedPropsForCapabilities(props, standalone)).toMatchObject({ assembly: 'hg38' });
    expect(seedPropsForCapabilities(props, fullCapabilities())).toMatchObject({ assembly: '' });
  });
});

describe('project fields', () => {
  it('sends the data management platform URL, trimmed, and checks its scheme', () => {
    let state = named(withTables('a'));
    expect(toProjectDraft(state)).not.toHaveProperty('data_management_platform_project_url');
    state = builderReducer(state, {
      type: 'project/patch',
      patch: { data_management_platform_project_url: ' https://dmp.example.org/p/1 ' },
    });
    expect(toProjectDraft(state).data_management_platform_project_url).toBe('https://dmp.example.org/p/1');
    state = builderReducer(state, {
      type: 'project/patch',
      patch: { data_management_platform_project_url: 'dmp/p/1' },
    });
    expect(errorCodes(state)).toContain('project_dmp_url');
  });
});

describe('wildcards', () => {
  const scan = (wildcards: { name: string; regex: string }[], regex = '^star/{sample}/quant\\.tsv$') => ({
    mode: 'recursive' as const,
    regex,
    wildcards,
  });

  it('accepts unique lowercase names each used in the regex', () => {
    expect(wildcardIssues(scan([{ name: 'sample', regex: '[^/]+' }]))).toEqual([]);
    expect(
      wildcardIssues(
        scan(
          [
            { name: 'sample', regex: '[^/]+' },
            { name: 'Lane_2', regex: 'L\\d' },
          ],
          '^{sample}/{Lane_2}\\.tsv$',
        ),
      ),
    ).toEqual([]);
  });

  it('refuses bad, duplicate, unused and template-variable names', () => {
    expect(wildcardIssues(scan([{ name: '1st', regex: '.+' }], '^{1st}$'))).toEqual([
      '“1st” is not a wildcard name: letters, digits and _, not starting with a digit.',
    ]);
    expect(wildcardIssues(scan([{ name: 'SAMPLE', regex: '[^/]+' }], '^star/{SAMPLE}/q$'))).toEqual([
      'Use a lowercase name: {SAMPLE} reads as a template variable.',
    ]);
    expect(
      wildcardIssues(
        scan([
          { name: 'sample', regex: '.+' },
          { name: 'sample', regex: '.+' },
        ]),
      ),
    ).toContain('Two wildcards are named “sample”.');
    expect(wildcardIssues(scan([{ name: 'lane', regex: '.+' }]))).toEqual([
      'The regex does not use {lane}: write it where its value sits in the path.',
    ]);
    expect(wildcardIssues(scan([{ name: 'sample', regex: ' ' }]))).toEqual(['Wildcard “sample” has no regex.']);
    expect(wildcardIssues(scan([{ name: '', regex: '.+' }]))).toEqual(['A wildcard has no name.']);
  });

  it('blocks the template on a bad wildcard and sends good ones, trimmed, for a scan only', () => {
    const dc: BuilderDcDraft = {
      ...table('quant'),
      mode: 'recursive',
      regex: '^star/{sample}/quant\\.tsv$',
      wildcards: [
        { name: ' sample ', regex: ' [^/]+ ' },
        { name: '', regex: '' },
      ],
    };
    expect(errorCodes(named(save(initialBuilderState(), dc)))).toEqual([]);
    expect(normalizeDcDraft(dc).wildcards).toEqual([{ name: 'sample', regex: '[^/]+' }]);
    expect(normalizeDcDraft({ ...dc, mode: 'single' })).not.toHaveProperty('wildcards');
    const bad = named(save(initialBuilderState(), { ...dc, wildcards: [{ name: 'SAMPLE', regex: '.+' }] }));
    expect(errorCodes(bad)).toContain('dc_wildcard_invalid');
  });
});

describe('table options', () => {
  const base = defaultDcProps('table', { path: 'sites.csv' }) as BuilderTableProps;

  it('needs both map coordinates or none, and sends both with the CRS', () => {
    expect(coordinatesIssue({ ...base, lat_column: 'lat' })).toBe(
      'Map coordinates need both a latitude and a longitude column.',
    );
    expect(coordinatesIssue({ ...base, lat_column: 'x', lon_column: 'x' })).toBe(
      'Latitude and longitude must be two different columns.',
    );
    expect(coordinatesIssue({ ...base, lat_column: 'lat', lon_column: 'lon' })).toBeNull();

    const partial: BuilderDcDraft = { ...table('sites'), props: { ...base, lat_column: 'lat', crs: 'EPSG:3857' } };
    expect(errorCodes(named(save(initialBuilderState(), partial)))).toEqual(['table_coordinates']);
    expect(normalizeDcDraft(partial).props).toEqual({ kind: 'table', format: 'csv', separator: ',' });

    const both: BuilderDcDraft = { ...partial, props: { ...base, lat_column: ' lat ', lon_column: 'lon', crs: ' ' } };
    expect(normalizeDcDraft(both).props).toEqual({
      kind: 'table',
      format: 'csv',
      separator: ',',
      lat_column: 'lat',
      lon_column: 'lon',
    });
    const withCrs: BuilderDcDraft = { ...both, props: { ...base, lat_column: 'lat', lon_column: 'lon', crs: 'EPSG:3857' } };
    expect(normalizeDcDraft(withCrs).props).toMatchObject({ crs: 'EPSG:3857' });
  });

  it('sends reader options for csv/tsv only, without defaults, as the server allows', () => {
    const reader = {
      has_header: false,
      skip_rows: 2,
      comment_prefix: '#',
      null_values: ['NA', ' ', '.'],
      quote_char: "'",
      decimal_comma: false,
    };
    const csv: BuilderDcDraft = { ...table('t'), props: { kind: 'table', format: 'csv', separator: ',', reader } };
    expect(normalizeDcDraft(csv).props).toMatchObject({
      reader: { has_header: false, skip_rows: 2, comment_prefix: '#', null_values: ['NA', '.'], quote_char: "'" },
    });
    const parquet: BuilderDcDraft = { ...csv, props: { kind: 'table', format: 'parquet', reader } };
    expect(normalizeDcDraft(parquet).props).not.toHaveProperty('reader');
    const defaults: BuilderDcDraft = {
      ...csv,
      props: { kind: 'table', format: 'tsv', reader: { has_header: true, skip_rows: 0, decimal_comma: false } },
    };
    expect(normalizeDcDraft(defaults).props).not.toHaveProperty('reader');
    // A server allowing only some options gets only those; one allowing none
    // (the v1 fallback) gets none.
    const limited = capabilities({ reader_options: ['separator', 'skip_rows'] });
    expect(normalizeDcDraft(csv, { capabilities: limited }).props).toEqual({
      kind: 'table',
      format: 'csv',
      separator: ',',
      reader: { skip_rows: 2 },
    });
    expect(normalizeDcDraft(csv, { capabilities: fallbackBuilderCapabilities() }).props).not.toHaveProperty('reader');
  });

  it('sends a SpatialData table with its store elements and nothing a text table has', () => {
    const dc: BuilderDcDraft = {
      tag: 'spots',
      type: 'table',
      mode: 'single',
      path: 'visium.zarr',
      metatype: 'Aggregate',
      props: {
        kind: 'table',
        format: 'spatialdata',
        separator: ',',
        reader: { skip_rows: 1 },
        lat_column: 'x',
        lon_column: 'y',
        spatialdata: {
          table: 'tables/table',
          image: ' images/hires ',
          coordinates: 'auto',
          genes: ['CD3E', ' '],
          layer: '',
        },
      },
    };
    expect(normalizeDcDraft(dc)).toEqual({
      tag: 'spots',
      type: 'table',
      mode: 'single',
      path: 'visium.zarr',
      metatype: 'Aggregate',
      props: {
        kind: 'table',
        format: 'spatialdata',
        spatialdata: { table: 'tables/table', image: 'images/hires', genes: ['CD3E'] },
      },
    });
    const obsm = { ...dc, props: { kind: 'table', format: 'spatialdata', spatialdata: { coordinates: 'obsm' } } } as BuilderDcDraft;
    expect(normalizeDcDraft(obsm).props).toEqual({ kind: 'table', format: 'spatialdata', spatialdata: { coordinates: 'obsm' } });
    expect(defaultDcProps('table', { path: 'visium.zarr' })).toEqual({
      kind: 'table',
      format: 'spatialdata',
      spatialdata: {},
    });
    const state = named(save(initialBuilderState(), dc));
    expect(errorCodes(state, { capabilities: capabilities() })).toEqual(['table_format_unavailable']);
    expect(errorCodes(state, { capabilities: fullCapabilities() })).toEqual([]);
    expect(errorCodes(state, { capabilities: fullCapabilities(), remote: true })).toEqual(['spatialdata_remote']);
  });

  it('sends a metatype only for the types that have one', () => {
    expect(normalizeDcDraft({ ...table('t'), metatype: 'Metadata' }).metatype).toBe('Metadata');
    expect(normalizeDcDraft({ ...table('t'), metatype: null })).not.toHaveProperty('metatype');
    const multiqc: BuilderDcDraft = { ...table('m'), type: 'multiqc', metatype: 'Aggregate', props: { kind: 'multiqc' } };
    expect(normalizeDcDraft(multiqc)).not.toHaveProperty('metatype');
  });

  it('sends the image options and checks the thumbnail size', () => {
    const dc: BuilderDcDraft = {
      tag: 'imgs',
      type: 'image',
      mode: 'single',
      path: 'images.tsv',
      props: {
        kind: 'image',
        format: 'mixed',
        image_column: 'file',
        local_images_path: 'images',
        s3_base_folder: '',
        columns_description: { file: 'the image', x: ' ' },
        thumbnail_size: 300,
        supported_formats: ['.png', ' '],
      },
    };
    expect(normalizeDcDraft(dc).props).toEqual({
      kind: 'image',
      format: 'mixed',
      image_column: 'file',
      local_images_path: 'images',
      columns_description: { file: 'the image' },
      thumbnail_size: 300,
      supported_formats: ['.png'],
    });
    const huge = named(save(initialBuilderState(), { ...dc, props: { ...dc.props, thumbnail_size: 2000 } as Props }));
    expect(errorCodes(huge)).toEqual(['image_thumbnail_size']);
    // Standalone: depictio ingest needs the S3 folder; a warning, not a refusal.
    const state = named(save(initialBuilderState(), dc));
    expect(validateBuilderState(state, { mode: 'standalone' })).toContainEqual(
      expect.objectContaining({ level: 'warning', code: 'image_s3_base_folder_missing' }),
    );
    expect(validateBuilderState(state, { mode: 'server' }).map((i) => i.code)).not.toContain(
      'image_s3_base_folder_missing',
    );
  });
});

describe('genomic tracks and bioimages', () => {
  it('sends a manifest with its columns and a preset assembly', () => {
    const dc = tracks('coverage', {
      metatype: 'Aggregate',
      props: {
        kind: 'genomic_tracks',
        format: 'tsv',
        separator: '\t',
        uri_column: ' uri ',
        sample_column: 'sample',
        format_column: '',
        index_column: 'index_uri',
        name_column: null,
        default_format: 'bigwig',
        assembly: ' hg38 ',
        tracks_base_path: '',
      },
    });
    expect(normalizeDcDraft(dc)).toEqual({
      tag: 'coverage',
      type: 'genomic_tracks',
      mode: 'single',
      path: 'tracks/manifest.tsv',
      metatype: 'Aggregate',
      props: {
        kind: 'genomic_tracks',
        format: 'tsv',
        separator: '\t',
        uri_column: 'uri',
        sample_column: 'sample',
        index_column: 'index_uri',
        default_format: 'bigwig',
        assembly: 'hg38',
        // '' is the data root: kept.
        tracks_base_path: '',
      },
    });
    // Absent: the manifest's own folder.
    const ownFolder = normalizeDcDraft({ ...dc, props: { ...dc.props, tracks_base_path: null } as Props });
    expect(ownFolder.props).not.toHaveProperty('tracks_base_path');
  });

  it('sends a custom assembly without its blanks, and needs it named', () => {
    const dc = tracks('coverage', {
      props: {
        kind: 'genomic_tracks',
        format: 'csv',
        uri_column: 'uri',
        assembly: {
          name: ' dm6 ',
          display_name: '',
          aliases: ['BDGP6', ' '],
          twobit_uri: 'genome/dm6.2bit',
          fasta_uri: ' ',
          chrom_sizes_uri: 'https://example.org/dm6.chrom.sizes',
        },
      },
    });
    expect(normalizeDcDraft(dc).props).toEqual({
      kind: 'genomic_tracks',
      format: 'csv',
      uri_column: 'uri',
      assembly: {
        name: 'dm6',
        aliases: ['BDGP6'],
        twobit_uri: 'genome/dm6.2bit',
        chrom_sizes_uri: 'https://example.org/dm6.chrom.sizes',
      },
    });
    const caps = fullCapabilities();
    const unnamed = named(
      save(initialBuilderState(), tracks('c', { props: { ...dc.props, assembly: { name: ' ' } } as Props })),
    );
    expect(blockingIssues(validateBuilderState(unnamed, { capabilities: caps })).map((i) => i.message)).toEqual([
      '“c”: Give the custom assembly a name.',
    ]);
    const none = named(save(initialBuilderState(), tracks('c', { props: { ...dc.props, assembly: '' } as Props })));
    expect(errorCodes(none, { capabilities: caps })).toEqual(['genomic_tracks_assembly']);
    const trackFile = named(save(initialBuilderState(), tracks('c', { path: 'bw/S1.bw' })));
    expect(errorCodes(trackFile, { capabilities: caps })).toEqual(['genomic_tracks_manifest_is_track']);
  });

  it('starts a manifest as TSV when a track file was picked', () => {
    expect(defaultDcProps('genomic_tracks', { path: 'bw/S1.bigwig', format: 'bigwig' })).toEqual({
      kind: 'genomic_tracks',
      format: 'tsv',
      separator: '\t',
      uri_column: 'uri',
      assembly: '',
    });
    expect(defaultDcProps('genomic_tracks', { path: 'tracks.csv' })).toMatchObject({ format: 'csv' });
  });

  it('sends a bioimage store with only what its format uses', () => {
    const dc: BuilderDcDraft = {
      tag: 'slides',
      type: 'bioimage',
      mode: 'recursive',
      regex: '.*\\.ome\\.zarr$',
      props: { kind: 'bioimage', format: 'ome-zarr', ngff_version: '0.4', upload: true, image_path: '' },
    };
    expect(normalizeDcDraft(dc)).toEqual({
      tag: 'slides',
      type: 'bioimage',
      mode: 'recursive',
      regex: '.*\\.ome\\.zarr$',
      props: { kind: 'bioimage', format: 'ome-zarr', ngff_version: '0.4' },
    });
    const tiff: BuilderDcDraft = {
      ...dc,
      props: { kind: 'bioimage', format: 'ome-tiff', ngff_version: '0.5', upload: false, image_path: 'images/x' },
    };
    expect(normalizeDcDraft(tiff).props).toEqual({ kind: 'bioimage', format: 'ome-tiff', upload: false });
    const spatial: BuilderDcDraft = {
      ...dc,
      props: { kind: 'bioimage', format: 'spatialdata', image_path: ' images/hires ' },
    };
    expect(normalizeDcDraft(spatial).props).toEqual({
      kind: 'bioimage',
      format: 'spatialdata',
      image_path: 'images/hires',
    });
    expect(defaultDcProps('bioimage', { path: 'a/slide.ome.tiff' })).toEqual({
      kind: 'bioimage',
      format: 'ome-tiff',
      upload: true,
    });

    const caps = fullCapabilities();
    const noImage = named(save(initialBuilderState(), { ...spatial, props: { kind: 'bioimage', format: 'spatialdata' } }));
    expect(errorCodes(noImage, { capabilities: caps })).toEqual(['bioimage_image_path']);
    const local = named(save(initialBuilderState(), dc));
    expect(errorCodes(local, { capabilities: caps })).toEqual([]);
    expect(errorCodes(local, { capabilities: caps, remote: true })).toEqual(['bioimage_remote']);
  });
});

describe('links', () => {
  const multiqc: BuilderDcDraft = {
    tag: 'qc',
    type: 'multiqc',
    mode: 'single',
    path: 'multiqc.parquet',
    props: { kind: 'multiqc' },
  };

  const linked = (): BuilderState => save(named(withTables('samples', 'quant')), multiqc);

  it('starts a link from the first source to the first allowed target', () => {
    const state = linked();
    expect(newLinkDraft(state, capabilities())).toEqual({
      source_tag: 'samples',
      source_column: '',
      target_tag: 'quant',
      resolver: 'direct',
      target_field: null,
    });
    // A server taking only MultiQC targets: sample mapping on sample_name.
    expect(newLinkDraft(state, capabilities({ link_target_types: ['multiqc'] }))).toMatchObject({
      target_tag: 'qc',
      resolver: 'sample_mapping',
      target_field: 'sample_name',
    });
  });

  it('checks tags, columns, the source and target types and the pattern', () => {
    let state = linked();
    state = builderReducer(state, {
      type: 'link/add',
      link: { source_tag: 'samples', source_column: '', target_tag: 'nope' },
    });
    state = builderReducer(state, {
      type: 'link/add',
      link: { source_tag: 'qc', source_column: 'sample', target_tag: 'quant', resolver: 'pattern', pattern: 'S_R1' },
    });
    state = builderReducer(state, {
      type: 'link/add',
      link: { source_tag: 'samples', source_column: 'sample', target_tag: 'qc', resolver: 'sample_mapping' },
    });
    const caps = capabilities({ link_target_types: ['table', 'image'] });
    const byLink = (i: number) =>
      linkIssues(state, caps)
        .filter((issue) => issue.linkIndex === i)
        .map((issue) => issue.code);
    expect(byLink(0)).toEqual(['link_source_column', 'link_target_missing']);
    expect(byLink(1)).toEqual(['link_source_type', 'link_pattern']);
    expect(byLink(2)).toEqual(['link_target_type']);
    expect(linkIssues(state, caps)[0].message).toBe('Link 1: pick the column it filters on.');
    // They block the template like any other rule.
    expect(errorCodes(state, { capabilities: caps })).toHaveLength(5);
  });

  it('sends links in the contract shape, follows renames and drops what cannot go', () => {
    let state = linked();
    state = builderReducer(state, {
      type: 'link/add',
      link: {
        source_tag: 'samples',
        source_column: ' sample ',
        target_tag: 'quant',
        resolver: 'direct',
        target_field: ' sample ',
        pattern: 'stale {sample}',
        description: ' ',
      },
    });
    state = builderReducer(state, {
      type: 'link/add',
      link: {
        source_tag: 'samples',
        source_column: 'sample',
        target_tag: 'qc',
        resolver: 'pattern',
        pattern: '{sample}_R1',
        target_field: '',
      },
    });
    const caps = capabilities();
    expect(errorCodes(state, { capabilities: caps })).toEqual([]);
    expect(toProjectDraft(state, { capabilities: caps }).links).toEqual([
      { source_tag: 'samples', source_column: 'sample', target_tag: 'quant', resolver: 'direct', target_field: 'sample' },
      { source_tag: 'samples', source_column: 'sample', target_tag: 'qc', resolver: 'pattern', pattern: '{sample}_R1' },
    ]);

    // Renaming a collection repoints its links.
    const quant = state.workflows[0].data_collections.find((dc) => dc.tag === 'quant') as BuilderDcDraft;
    state = builderReducer(state, {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: { ...quant, tag: 'counts' },
      originalTag: 'quant',
    });
    expect(state.links[0].target_tag).toBe('counts');

    // A server refusing MultiQC targets never gets that link.
    expect(toProjectDraft(state, { capabilities: capabilities({ link_target_types: ['table'] }) }).links).toHaveLength(1);
    // A removed collection's links stay in the draft, flagged, and are not sent.
    state = builderReducer(state, { type: 'dc/remove', tag: 'counts' });
    expect(state.links).toHaveLength(2);
    expect(linkIssues(state, caps).map((i) => i.code)).toEqual(['link_target_missing']);
    expect(toProjectDraft(state, { capabilities: caps }).links).toHaveLength(1);
    state = builderReducer(state, { type: 'link/remove', index: 0 });
    state = builderReducer(state, { type: 'link/patch', index: 0, patch: { description: 'QC per sample' } });
    expect(state.links).toEqual([
      {
        source_tag: 'samples',
        source_column: 'sample',
        target_tag: 'qc',
        resolver: 'pattern',
        pattern: '{sample}_R1',
        target_field: '',
        description: 'QC per sample',
      },
    ]);
  });

  it('keeps each collection schema for the column pickers, and forgets it with the collection', () => {
    let state = builderReducer(initialBuilderState(), {
      type: 'dc/save',
      workflowId: 'wf-0',
      dc: table('samples'),
      schema: { sample: 'String', site: 'String' },
    });
    expect(state.schemas.samples).toEqual({ sample: 'String', site: 'String' });
    state = builderReducer(state, { type: 'dc/save', workflowId: 'wf-0', dc: table('meta'), originalTag: 'samples' });
    expect(state.schemas).toEqual({ meta: { sample: 'String', site: 'String' } });
    state = builderReducer(state, { type: 'dc/remove', tag: 'meta' });
    expect(state.schemas).toEqual({});
  });
});

describe('v2 draft persistence', () => {
  it('loads a draft saved before links and the v2 fields', () => {
    const old = {
      version: 1,
      project: { name: 'P', description: '', is_public: false, realtime: true },
      workflows: [{ id: 'wf-0', name: 'main', engine: 'python', structure: 'flat', data_collections: [table('a')] }],
      activeWorkflowId: 'wf-0',
      claimed: { a: ['a.csv'] },
      nextId: 1,
    };
    const parsed = parseBuilderState(old);
    expect(parsed?.links).toEqual([]);
    expect(parsed?.schemas).toEqual({});
    expect(parsed?.project.data_management_platform_project_url).toBe('');
    expect(parsed?.project.realtime).toBe(true);
    expect(parsed?.workflows[0].data_collections[0].tag).toBe('a');
  });

  it('round-trips links, schemas, wildcards and the new types', () => {
    const storage = memoryStorage();
    let state = named(save(withTables('samples'), tracks('coverage')));
    state = builderReducer(state, { type: 'dc/schema', tag: 'samples', schema: { sample: 'String' } });
    state = builderReducer(state, {
      type: 'link/add',
      link: { source_tag: 'samples', source_column: 'sample', target_tag: 'coverage', resolver: 'direct' },
    });
    state = save(state, {
      ...table('scan'),
      mode: 'recursive',
      regex: '^{sample}\\.csv$',
      wildcards: [{ name: 'sample', regex: '.+' }],
    });
    saveBuilderDraft('/d', state, storage);
    expect(loadBuilderDraft('/d', storage)).toEqual(state);
  });
});

describe('v2 builder calls', () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];

  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const body = (i: number) => JSON.parse(String(calls[i].init.body));

  it('reads the capabilities and posts the manifest routes', async () => {
    await builderCapabilities();
    expect(calls[0].url).toBe('/depictio/api/v1/projects/builder/capabilities');
    expect(calls[0].init.method ?? 'GET').toBe('GET');

    await builderTracksManifest({ data_root: '/d' }, ['bw/S1.bw', 'bw/S2.bw']);
    expect(calls[1].url).toBe('/depictio/api/v1/projects/builder/tracks_manifest');
    expect(body(1)).toEqual({ root: { data_root: '/d' }, files: ['bw/S1.bw', 'bw/S2.bw'] });

    await builderTracksManifest({ data_root: '/d' }, ['bw/S1.bw'], '(?P<sample>S\\d)');
    expect(body(2).sample_regex).toBe('(?P<sample>S\\d)');

    await builderWriteManifest('coverage_manifest', 'uri\nbw/S1.bw\n');
    expect(calls[3].url).toBe('/depictio/api/v1/projects/builder/write_manifest');
    expect(body(3)).toEqual({ name: 'coverage_manifest', tsv: 'uri\nbw/S1.bw\n' });
    await builderWriteManifest('coverage_manifest', 'x', true);
    expect(body(4).overwrite).toBe(true);
  });
});

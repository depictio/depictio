import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { builderMatch, builderTemplate, builderTree, createProjectFromRun, previewRunFile } from './api';
import {
  BUILDER_HANDOFF_KEY,
  builderDraftKey,
  builderReducer,
  clearBuilderDraft,
  defaultDcProps,
  globToRegex,
  initialBuilderState,
  isTagTaken,
  loadBuilderDraft,
  normalizeDcDraft,
  parseBuilderState,
  regexToGlob,
  saveBuilderDraft,
  tableTags,
  tagFromPath,
  takeBuilderHandoff,
  toProjectDraft,
  uniqueTag,
  validateBuilderState,
  writeBuilderHandoff,
} from './projectBuilder';
import type { BuilderDcDraft, BuilderState, BuilderStorage } from './projectBuilder';

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

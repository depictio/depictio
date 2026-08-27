import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  renderIdsIn,
  openAddRendersPr,
  openCatalogPr,
  resolveTarget,
  DEFAULT_TARGET,
} from '../catalog/github';
import type { GeneratedEntry } from '../catalog/yamlGen';
import type { RenderSpec } from '../types';

/**
 * A GitHub stub covering the whole fork → branch → blobs → tree → commit → PR
 * sequence, so the PR machinery (307 lines that previously had no test at any
 * level) can be exercised without a token. `files` is what the upstream repo
 * contains at the base commit; `blobs` collects what the flow tried to commit.
 */
function mockGitHub(files: Record<string, string> = {}) {
  const blobs: string[] = [];
  const trees: Array<{ path: string; sha: string }[]> = [];
  let prBody = '';
  const calls: string[] = [];

  const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = typeof url === 'string' ? url : url.toString();
    const method = init?.method ?? 'GET';
    const path = u.replace('https://api.github.com', '');
    calls.push(`${method} ${path}`);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

    if (path === '/user') return json({ login: 'contributor' });
    if (method === 'POST' && path.endsWith('/forks')) return json({});
    if (path.includes('/git/ref/heads/')) return json({ object: { sha: 'basesha' } });
    if (path.includes('/git/commits/basesha')) return json({ tree: { sha: 'basetree' } });
    if (path.startsWith('/repos/depictio/depictio/contents/')) {
      const filePath = decodeURIComponent(path.split('/contents/')[1].split('?')[0]);
      const content = files[filePath];
      if (content == null) return json({ message: 'Not Found' }, 404);
      return json({ encoding: 'base64', content: btoa(content) });
    }
    if (method === 'POST' && path.endsWith('/git/blobs')) {
      blobs.push(JSON.parse(String(init?.body)).content);
      return json({ sha: `blob${blobs.length}` });
    }
    if (method === 'POST' && path.endsWith('/git/trees')) {
      trees.push(JSON.parse(String(init?.body)).tree);
      return json({ sha: 'newtree' });
    }
    if (method === 'POST' && path.endsWith('/git/commits')) return json({ sha: 'newcommit' });
    if (method === 'POST' && path.endsWith('/git/refs')) return json({});
    if (method === 'PATCH' && path.includes('/git/refs/heads/')) return json({});
    if (method === 'POST' && path.endsWith('/pulls')) {
      prBody = JSON.parse(String(init?.body)).body;
      return json({ html_url: 'https://github.com/depictio/depictio/pull/1' });
    }
    return json({ message: `unhandled ${method} ${path}` }, 500);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { blobs, trees, calls, prBody: () => prBody };
}

afterEach(() => vi.unstubAllGlobals());

const UPSTREAM = `id: mosdepth_coverage
find: {path_glob: "**/mosdepth/*.txt"}
fixture: coverage.tsv
renders_as:
  - { id: existing_card, component: card, column: mean, aggregation: average }
`;

const newRenders: RenderSpec[] = [
  { uid: 'r1', component: 'card', id: 'fresh_card', column: 'mean', aggregation: 'median' },
];

describe('renderIdsIn', () => {
  it('finds ids in both flow and block items', () => {
    const yaml = `renders_as:
  - { id: flow_one, component: table }
  - id: block_one
    component: card
`;
    expect([...renderIdsIn(yaml)].sort()).toEqual(['block_one', 'flow_one']);
  });

  it('returns an empty set for a file with no ids', () => {
    expect(renderIdsIn('renders_as:\n  - { component: table }\n').size).toBe(0);
  });
});

describe('openAddRendersPr', () => {
  it('appends to the LIVE file, not to the snapshot it previewed', async () => {
    // The snapshot the Studio was built with is missing a render that has since
    // been merged. Committing the snapshot-derived text would delete it.
    const staleSnapshot = UPSTREAM.replace(
      '  - { id: existing_card, component: card, column: mean, aggregation: average }\n',
      '',
    );
    const gh = mockGitHub({ 'depictio/catalog/mosdepth/coverage.yaml': UPSTREAM });

    await openAddRendersPr('tok', {
      toolId: 'mosdepth',
      outputSlug: 'coverage',
      yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
      renders: newRenders,
      snapshotYaml: staleSnapshot,
    });

    expect(gh.blobs).toHaveLength(1);
    expect(gh.blobs[0]).toContain('id: existing_card'); // preserved
    expect(gh.blobs[0]).toContain('id: fresh_card'); // appended
  });

  it('notes the rebase in the PR body when the snapshot had drifted', async () => {
    const gh = mockGitHub({ 'depictio/catalog/mosdepth/coverage.yaml': UPSTREAM });
    await openAddRendersPr('tok', {
      toolId: 'mosdepth',
      outputSlug: 'coverage',
      yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
      renders: newRenders,
      snapshotYaml: 'id: mosdepth_coverage\nrenders_as: []\n',
    });
    expect(gh.prBody()).toContain('had changed upstream');
  });

  it('says nothing about drift when the snapshot was current', async () => {
    const gh = mockGitHub({ 'depictio/catalog/mosdepth/coverage.yaml': UPSTREAM });
    await openAddRendersPr('tok', {
      toolId: 'mosdepth',
      outputSlug: 'coverage',
      yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
      renders: newRenders,
      snapshotYaml: UPSTREAM,
    });
    expect(gh.prBody()).not.toContain('had changed upstream');
  });

  it('refuses when the target file is gone upstream', async () => {
    mockGitHub({}); // no such file
    await expect(
      openAddRendersPr('tok', {
        toolId: 'mosdepth',
        outputSlug: 'coverage',
        yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
        renders: newRenders,
      }),
    ).rejects.toThrow(/no longer exists/);
  });

  it('refuses when a render id already exists upstream', async () => {
    mockGitHub({ 'depictio/catalog/mosdepth/coverage.yaml': UPSTREAM });
    await expect(
      openAddRendersPr('tok', {
        toolId: 'mosdepth',
        outputSlug: 'coverage',
        yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
        renders: [{ ...newRenders[0], id: 'existing_card' }],
      }),
    ).rejects.toThrow(/already exists/);
  });

  it('never commits before it has read the current file', async () => {
    const gh = mockGitHub({ 'depictio/catalog/mosdepth/coverage.yaml': UPSTREAM });
    await openAddRendersPr('tok', {
      toolId: 'mosdepth',
      outputSlug: 'coverage',
      yamlPath: 'depictio/catalog/mosdepth/coverage.yaml',
      renders: newRenders,
    });
    const readAt = gh.calls.findIndex((c) => c.includes('/contents/'));
    const blobAt = gh.calls.findIndex((c) => c.includes('/git/blobs'));
    expect(readAt).toBeGreaterThanOrEqual(0);
    expect(readAt).toBeLessThan(blobAt);
  });
});

describe('openCatalogPr', () => {
  const entry: GeneratedEntry = {
    toolId: 'newtool',
    outputSlug: 'results',
    moduleYaml: 'id: newtool\nname: New Tool\n',
    outputYamlName: 'results.yaml',
    outputYaml: 'id: newtool_results\n',
    fixtureName: 'results.csv',
    fixtureContent: 'a,b\n1,2\n',
  };

  it('commits the three files under the tool folder', async () => {
    const gh = mockGitHub();
    const res = await openCatalogPr('tok', entry);
    expect(res.prUrl).toContain('/pull/1');
    expect(gh.trees[0].map((t) => t.path)).toEqual([
      'depictio/catalog/newtool/module.yaml',
      'depictio/catalog/newtool/results.yaml',
      'depictio/catalog/newtool/results.csv',
    ]);
  });
});

describe('resolveTarget', () => {
  it('falls back to depictio/depictio@main', () => {
    expect(resolveTarget()).toEqual(DEFAULT_TARGET);
  });
});

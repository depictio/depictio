/**
 * Append mode through the agent surface: exportFiles returns the spliced YAML
 * under its repo path, getDraft/link record the target (`appendTo`), and a
 * draft carrying one re-enters append mode from the catalog snapshot, or is
 * refused when the output is not in it. Also: outputs without a fixture are
 * named for the Export step rather than dropped.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import yaml from 'js-yaml';
import { __setAgentCatalogForTests, applyDraft, toolFiles } from '../agentApi';
import { normalizeDraft, toDraft } from '../catalog/draft';
import { outputsWithoutFixture, useStudioStore } from '../state/useStudioStore';
import type { CatalogManifest } from '../catalog/catalog';

const RAW = 'id: t_o\nfind: { path_glob: "*.csv" }\nfixture: o.csv\nrenders_as:\n  - { id: base_table, component: table }\n';
const catalog: CatalogManifest = {
  tools: [
    {
      id: 't',
      name: 'T',
      outputs: [
        {
          id: 't_o',
          slug: 'o',
          path_glob: '*.csv',
          renders_as: [{ id: 'base_table', component: 'table' }],
          fixture: 'o.csv',
          fixtureContent: 'gene,v\nA,1\n',
          yamlPath: 'depictio/catalog/t/o.yaml',
          rawYaml: RAW,
        },
      ],
    },
  ],
};
const newCard = { component: 'card', id: 'v_avg', column: 'v', aggregation: 'average' } as const;

beforeEach(() => {
  localStorage.clear();
  useStudioStore.getState().reset();
  __setAgentCatalogForTests(catalog);
});

describe('append mode via the agent API', () => {
  it('exportFiles returns the appended YAML under the output’s repo path', () => {
    useStudioStore.getState().startExisting(catalog.tools[0], catalog.tools[0].outputs[0]);
    useStudioStore.getState().addRender({ ...newCard, uid: 'u1' });
    const files = toolFiles();
    expect(Object.keys(files)).toEqual(['depictio/catalog/t/o.yaml']);
    const doc = yaml.load(files['depictio/catalog/t/o.yaml']) as { renders_as: Array<{ id?: string }> };
    expect(doc.renders_as.map((r) => r.id)).toEqual(['base_table', 'v_avg']);
  });

  it('getDraft records the append target, and loading it re-enters append mode', () => {
    useStudioStore.getState().startExisting(catalog.tools[0], catalog.tools[0].outputs[0]);
    useStudioStore.getState().addRender({ ...newCard, uid: 'u1' });
    const d = toDraft(useStudioStore.getState());
    expect(d.appendTo).toEqual({ toolId: 't', outputId: 't_o', yamlPath: 'depictio/catalog/t/o.yaml' });
    useStudioStore.getState().reset();
    applyDraft(normalizeDraft(JSON.parse(JSON.stringify(d))));
    const s = useStudioStore.getState();
    expect(s.existing?.yamlPath).toBe('depictio/catalog/t/o.yaml');
    expect(s.renders.map((r) => r.id)).toEqual(['v_avg']);
    expect(Object.keys(toolFiles())).toEqual(['depictio/catalog/t/o.yaml']);
  });

  it('refuses an append draft whose output is not in the catalog', () => {
    const d = normalizeDraft({
      format: 'depictio-tool-studio/draft@1',
      tool: { id: 'gone' },
      output: { slug: 'x' },
      renders: [],
      appendTo: { toolId: 'gone', outputId: 'gone_x', yamlPath: 'depictio/catalog/gone/x.yaml' },
    });
    expect(() => applyDraft(d)).toThrow(/not in this build's catalog/);
    __setAgentCatalogForTests(undefined);
    expect(() => applyDraft(d)).toThrow(/catalog snapshot/);
  });
});

describe('outputs without a fixture', () => {
  it('are named, in order; none in append mode', () => {
    const s = useStudioStore.getState();
    s.setOutput({ slug: 'a' });
    s.addOutput();
    s.setOutput({ slug: 'b' });
    expect(outputsWithoutFixture(useStudioStore.getState())).toEqual(['a', 'b']);
    useStudioStore.getState().startExisting(catalog.tools[0], catalog.tools[0].outputs[0]);
    expect(outputsWithoutFixture(useStudioStore.getState())).toEqual([]);
  });
});

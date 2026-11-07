/**
 * What a project is made of, in the words of someone who brought data to it:
 * many runs of a pipeline (a core facility, a large study), the output of one
 * pipeline run, or tables and files added by hand.
 *
 * Detected from the project's workflows, not chosen up front: the UI makes a
 * synthetic Python workflow around every data collection a person adds by
 * hand, so "has workflows" says nothing. A real workflow names a pipeline
 * engine or a catalog entry, and runs are what an ingestion found. The owner
 * can override a wrong guess (`project.layout`).
 */
import type { ProjectListEntry } from 'depictio-react-core';

type LayoutInput = Pick<ProjectListEntry, 'workflows' | 'layout'> & {
  template_origin?: unknown;
};

export type ProjectLayoutKind = 'runs' | 'pipeline' | 'tables';

export const LAYOUT_KINDS: ProjectLayoutKind[] = ['runs', 'pipeline', 'tables'];

export interface ProjectLayout {
  kind: ProjectLayoutKind;
  /** The owner chose it; detection was not used. */
  overridden: boolean;
  /** Runs found by ingestion, across the pipelines (0 when none is recorded). */
  runCount: number;
  /** Names of the real pipelines, deduplicated. */
  pipelines: string[];
}

export const LAYOUT_COPY: Record<
  ProjectLayoutKind,
  { label: string; hint: string }
> = {
  runs: {
    label: 'Runs',
    hint: 'Many runs of a pipeline, compared side by side',
  },
  pipeline: {
    label: 'Pipeline output',
    hint: 'The output of one pipeline run',
  },
  tables: {
    label: 'Tables',
    hint: 'Files and tables added directly',
  },
};

interface WorkflowLike {
  data_collections?: unknown;
  name?: unknown;
  workflow_tag?: unknown;
  engine?: unknown;
  catalog?: unknown;
  runs?: unknown;
  data_location?: { structure?: unknown; locations?: unknown } | null;
}

function engineName(wf: WorkflowLike): string {
  const e = wf.engine;
  if (typeof e === 'string') return e.toLowerCase();
  if (e && typeof e === 'object') {
    const n = (e as { name?: unknown }).name;
    if (typeof n === 'string') return n.toLowerCase();
  }
  return '';
}

/** A workflow the UI did not make up: it names a pipeline engine or a catalog. */
function isRealWorkflow(wf: WorkflowLike): boolean {
  const engine = engineName(wf);
  return Boolean(wf.catalog) || (engine !== '' && engine !== 'python');
}

function workflowName(wf: WorkflowLike): string {
  for (const v of [wf.workflow_tag, wf.name]) {
    if (typeof v === 'string' && v) return v;
  }
  return engineName(wf) || 'workflow';
}

export function projectLayout(project: LayoutInput): ProjectLayout {
  const real = ((project.workflows ?? []) as WorkflowLike[]).filter(isRealWorkflow);
  const runCount = real.reduce((n, wf) => {
    const runs = wf.runs;
    return n + (runs && typeof runs === 'object' ? Object.keys(runs).length : 0);
  }, 0);
  const multiRunLayout = real.some(
    (wf) => wf.data_location?.structure === 'sequencing-runs',
  );
  const pipelines = [...new Set(real.map(workflowName))];

  const override = project.layout;
  if (override === 'runs' || override === 'pipeline' || override === 'tables') {
    return { kind: override, overridden: true, runCount, pipelines };
  }
  const kind: ProjectLayoutKind =
    runCount > 1 || multiRunLayout ? 'runs' : real.length > 0 ? 'pipeline' : 'tables';
  return { kind, overridden: false, runCount, pipelines };
}

/** One line under the badge: what was found, so the label is not a guess. */
export function layoutDetail(layout: ProjectLayout): string {
  const names = layout.pipelines.slice(0, 2).join(', ');
  const more = layout.pipelines.length > 2 ? ` and ${layout.pipelines.length - 2} more` : '';
  if (layout.kind === 'runs') {
    const runs = layout.runCount > 0 ? `${layout.runCount} runs` : 'Runs';
    return names ? `${runs} of ${names}${more}` : runs;
  }
  if (layout.kind === 'pipeline') {
    return names ? `Output of ${names}${more}` : LAYOUT_COPY.pipeline.hint;
  }
  return LAYOUT_COPY.tables.hint;
}

/* ------------------------------------------------------------------ */
/* The three facts under the sentence: where the data is, how many runs */
/* it holds, and which pipeline made it. Read from what is stored, so   */
/* they describe the project as it is, not as it was created.           */
/* ------------------------------------------------------------------ */

export type FacetKey = 'source' | 'runs' | 'pipeline';

export interface LayoutFacet {
  key: FacetKey;
  label: string;
  value: string;
  /** A path or version shown next to the value. */
  detail?: string;
  /** Worth drawing the eye to (a bucket, several runs, a known pipeline). */
  strong: boolean;
}

type SourceKind = 's3' | 'url' | 'upload' | 'folder';

const SOURCE_LABEL: Record<SourceKind, string> = {
  s3: 'S3',
  url: 'URL',
  upload: 'Upload',
  folder: 'Server folder',
};

/** An upload is stored as a single file in a temporary directory of the
 *  server, so it reads as a folder. Telling them apart by the directory is a
 *  heuristic: the collection records no explicit source yet. */
const TEMP_DIR = /^\/(tmp|var\/folders|private\/(var|tmp))\//;

function classifySource(place: string): SourceKind {
  if (/^s3:\/\//i.test(place)) return 's3';
  if (/^https?:\/\//i.test(place)) return 'url';
  if (TEMP_DIR.test(place)) return 'upload';
  return 'folder';
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null;
}

/** Every place the project reads data from: workflow locations, the folder a
 *  template was applied to, and the URLs its collections are scanned from. */
function sourcePlaces(project: LayoutInput): string[] {
  const places: string[] = [];
  const origin = project.template_origin as { data_root?: unknown } | null | undefined;
  const root = str(origin?.data_root);
  if (root) places.push(root);
  for (const wf of (project.workflows ?? []) as WorkflowLike[]) {
    const locations = wf.data_location?.locations;
    if (Array.isArray(locations)) {
      for (const l of locations) {
        const v = str(l);
        if (v) places.push(v);
      }
    }
    const dcs = Array.isArray(wf.data_collections) ? wf.data_collections : [];
    for (const dc of dcs as Array<{ config?: { scan?: { scan_parameters?: Record<string, unknown> } } }>) {
      const params = dc.config?.scan?.scan_parameters;
      for (const key of ['url', 'manifest_url']) {
        const v = str(params?.[key]);
        if (v) places.push(v);
      }
    }
  }
  return [...new Set(places)];
}

/** "nf-core/ampliseq/2.16.0" -> the pipeline and its version. */
function splitTemplateId(id: string): { name: string; version: string | null } {
  const parts = id.split('/');
  const last = parts[parts.length - 1];
  if (parts.length > 2 && /^\d/.test(last)) {
    return { name: parts.slice(0, -1).join('/'), version: last };
  }
  return { name: id, version: null };
}

export function layoutFacets(project: LayoutInput, layout: ProjectLayout): LayoutFacet[] {
  const places = sourcePlaces(project);
  const kinds = [...new Set(places.map(classifySource))];
  const firstPath = places.find((p) => classifySource(p) !== 'upload');
  const source: LayoutFacet = {
    key: 'source',
    label: 'Source',
    value: kinds.length > 0 ? kinds.map((k) => SOURCE_LABEL[k]).join(' + ') : 'Not recorded',
    detail: kinds.length === 1 && kinds[0] !== 'upload' ? firstPath : undefined,
    strong: kinds.includes('s3'),
  };

  const runs: LayoutFacet = {
    key: 'runs',
    label: 'Runs',
    value:
      layout.runCount > 0
        ? String(layout.runCount)
        : layout.kind === 'runs'
          ? 'Several'
          : layout.kind === 'pipeline'
            ? '1'
            : 'None',
    strong: layout.kind === 'runs',
  };

  const originId = str((project.template_origin as { template_id?: unknown } | null)?.template_id);
  let pipeline: LayoutFacet;
  if (originId) {
    const { name, version } = splitTemplateId(originId);
    pipeline = { key: 'pipeline', label: 'Pipeline', value: name, detail: version ?? undefined, strong: true };
  } else if (layout.pipelines.length > 0) {
    pipeline = {
      key: 'pipeline',
      label: 'Pipeline',
      value: layout.pipelines.slice(0, 2).join(', '),
      strong: true,
    };
  } else {
    pipeline = { key: 'pipeline', label: 'Pipeline', value: 'None', strong: false };
  }
  return [source, runs, pipeline];
}

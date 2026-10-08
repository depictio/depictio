/**
 * The template catalog as the "From a run folder" flow offers it: one entry
 * per pipeline, its versions newest first, and how a chosen template relates
 * to the run it is applied to.
 *
 * Two versions are in play and the flow keeps them apart everywhere:
 *  - the pipeline version OF THE RUN: which release of the pipeline produced
 *    the folder (read from the run's own records);
 *  - the template version: which release of the pipeline a Depictio template
 *    was written for, i.e. the version segment of its id
 *    (`nf-core/ampliseq/2.16.0`). Not `TemplateInfo.version`, which is the
 *    template's own revision and means nothing to someone picking one.
 */

/** The catalog fields this module reads (a subset of `TemplateInfo`). */
export interface RunTemplateEntry {
  template_id: string;
  name: string;
  description?: string | null;
  run_folder_capable?: boolean;
  source?: string | null;
  pipeline?: string | null;
  engine?: string | null;
}

export interface TemplateIdParts {
  /** First segment, e.g. `nf-core`. */
  source: string;
  /** Segments before the version, e.g. `nf-core/ampliseq`. */
  pipeline: string;
  /** The version segment, e.g. `2.16.0`; null when the id names none. */
  version: string | null;
  /** Segments after the version (`categories/indel`), null when none: a
   *  family of templates sharing one pipeline version. */
  variant: string | null;
}

const VERSION_SEGMENT = /^v?\d/i;

/** Split a template id into source, pipeline, version and variant. The
 *  version is the first segment after `source/name` that starts with a digit
 *  (optionally after a `v`). */
export function splitTemplateId(templateId: string): TemplateIdParts {
  const segments = templateId
    .split('/')
    .map((s) => s.trim())
    .filter(Boolean);
  let versionIndex = -1;
  for (let i = 2; i < segments.length; i += 1) {
    if (VERSION_SEGMENT.test(segments[i])) {
      versionIndex = i;
      break;
    }
  }
  const source = segments[0] ?? templateId;
  if (versionIndex < 0) {
    return { source, pipeline: segments.join('/'), version: null, variant: null };
  }
  return {
    source,
    pipeline: segments.slice(0, versionIndex).join('/'),
    version: segments[versionIndex],
    variant: segments.slice(versionIndex + 1).join('/') || null,
  };
}

/** A version without surrounding spaces or a leading `v`. */
function bareVersion(version: string): string {
  return version.trim().replace(/^v/i, '');
}

function versionKey(version: string): { main: number[]; pre: string | null } {
  const bare = bareVersion(version);
  const dash = bare.indexOf('-');
  const main = dash >= 0 ? bare.slice(0, dash) : bare;
  const pre = dash >= 0 ? bare.slice(dash + 1) : null;
  return {
    main: main.split(/[.+]/).map((part) => {
      const n = Number.parseInt(part, 10);
      return Number.isNaN(n) ? -1 : n;
    }),
    pre,
  };
}

/** Compare two version strings: positive when `a` is newer. Numeric segment
 *  by segment (`2.10.0` after `2.9.1`), a missing segment counting as 0, and
 *  a pre-release (`2.0.0-rc1`) before its release. */
export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a);
  const kb = versionKey(b);
  const length = Math.max(ka.main.length, kb.main.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (ka.main[i] ?? 0) - (kb.main[i] ?? 0);
    if (diff !== 0) return diff;
  }
  if (ka.pre === kb.pre) return 0;
  if (ka.pre === null) return 1;
  if (kb.pre === null) return -1;
  return ka.pre.localeCompare(kb.pre, undefined, { numeric: true });
}

/** Same release, ignoring a leading `v` and surrounding spaces. */
export function sameVersion(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  return bareVersion(a) === bareVersion(b);
}

/** `v2.16.0` from `2.16.0` or `v2.16.0`. */
export function formatVersion(version: string): string {
  return `v${bareVersion(version)}`;
}

export interface RunTemplateVersion {
  templateId: string;
  /** Pipeline version the template targets; null when its id names none. */
  version: string | null;
  name: string;
  description: string | null;
  /** The newest version of its pipeline. */
  latest: boolean;
}

export interface RunPipeline {
  /** Stable key of the entry: the pipeline, plus the variant when the
   *  template family has one. */
  key: string;
  source: string;
  /** e.g. `nf-core/ampliseq`. */
  pipeline: string;
  variant: string | null;
  /** The newest version's template name. */
  title: string;
  engine: string | null;
  /** Newest first. */
  versions: RunTemplateVersion[];
}

export interface RunPipelineGroup {
  source: string;
  /** How the source is written in a picker group heading. */
  label: string;
  pipelines: RunPipeline[];
}

const SOURCE_LABELS: Record<string, string> = {
  'nf-core': 'nf-core',
  generic: 'Generic',
  galaxy: 'Galaxy',
  iwc: 'IWC',
  'snakemake-workflows': 'Snakemake workflows',
  depictio: 'Depictio',
};

/** A source as written in a group heading. */
export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source.toLowerCase()] ?? source;
}

/** Can the template back a project made from a run folder? The catalog says
 *  so (`run_folder_capable`); a catalog that predates the flag offers every
 *  template but the internal `init/*` ones. */
export function isRunFolderCapable(template: RunTemplateEntry): boolean {
  if (typeof template.run_folder_capable === 'boolean') return template.run_folder_capable;
  return !template.template_id.startsWith('init/');
}

function pipelineKeyOf(parts: TemplateIdParts): string {
  return parts.variant ? `${parts.pipeline}/${parts.variant}` : parts.pipeline;
}

/** The catalog as one entry per pipeline, grouped by source.
 *
 *  Only run-folder-capable templates are kept, plus any id in `include` (a
 *  template detected in the folder or chosen earlier must stay pickable even
 *  if the catalog leaves it out). Versions are newest first, the first one
 *  marked `latest`. Groups come nf-core first then by label; pipelines by
 *  title. */
export function groupRunTemplates(
  templates: ReadonlyArray<RunTemplateEntry>,
  include: ReadonlyArray<string> = [],
): RunPipelineGroup[] {
  const kept = templates.filter(
    (t) => isRunFolderCapable(t) || include.includes(t.template_id),
  );
  for (const id of include) {
    if (id && !kept.some((t) => t.template_id === id)) {
      kept.push({ template_id: id, name: id });
    }
  }

  const pipelines = new Map<string, RunPipeline>();
  for (const t of kept) {
    const parts = splitTemplateId(t.template_id);
    const source = t.source || parts.source;
    const key = pipelineKeyOf(parts);
    let entry = pipelines.get(key);
    if (!entry) {
      entry = {
        key,
        source,
        pipeline: parts.pipeline,
        variant: parts.variant,
        title: t.name,
        engine: t.engine ?? null,
        versions: [],
      };
      pipelines.set(key, entry);
    }
    if (!entry.engine && t.engine) entry.engine = t.engine;
    entry.versions.push({
      templateId: t.template_id,
      version: parts.version,
      name: t.name,
      description: t.description ?? null,
      latest: false,
    });
  }

  for (const entry of pipelines.values()) {
    entry.versions.sort((a, b) => {
      if (a.version && b.version) return compareVersions(b.version, a.version);
      if (a.version) return -1;
      if (b.version) return 1;
      return a.templateId.localeCompare(b.templateId);
    });
    if (entry.versions[0]?.version) entry.versions[0].latest = true;
    entry.title = entry.versions[0]?.name ?? entry.title;
  }

  const groups = new Map<string, RunPipelineGroup>();
  for (const entry of pipelines.values()) {
    const id = entry.source.toLowerCase();
    let group = groups.get(id);
    if (!group) {
      group = { source: entry.source, label: sourceLabel(entry.source), pipelines: [] };
      groups.set(id, group);
    }
    group.pipelines.push(entry);
  }
  const ordered = [...groups.values()];
  for (const group of ordered) {
    group.pipelines.sort((a, b) => a.title.localeCompare(b.title));
  }
  ordered.sort((a, b) => {
    if (a.source.toLowerCase() === 'nf-core') return -1;
    if (b.source.toLowerCase() === 'nf-core') return 1;
    return a.label.localeCompare(b.label);
  });
  return ordered;
}

/** The pipeline entry offering `templateId`, or null. */
export function findRunPipeline(
  groups: ReadonlyArray<RunPipelineGroup>,
  templateId: string | null | undefined,
): RunPipeline | null {
  if (!templateId) return null;
  for (const group of groups) {
    for (const pipeline of group.pipelines) {
      if (pipeline.versions.some((v) => v.templateId === templateId)) return pipeline;
    }
  }
  return null;
}

/** The template a pipeline falls back to when picked: the one detected in
 *  the folder when it belongs to that pipeline, else the version matching the
 *  run, else the newest. */
export function defaultVersionFor(
  pipeline: RunPipeline,
  options: { detectedTemplateId?: string | null; runVersion?: string | null } = {},
): string | null {
  const { detectedTemplateId, runVersion } = options;
  if (detectedTemplateId && pipeline.versions.some((v) => v.templateId === detectedTemplateId)) {
    return detectedTemplateId;
  }
  const matching = pipeline.versions.find((v) => sameVersion(v.version, runVersion));
  if (matching) return matching.templateId;
  return pipeline.versions[0]?.templateId ?? null;
}

/** How the template in use relates to the run:
 *  - `exact`: same pipeline, the template targets the run's version;
 *  - `closest`: the version detection picked because the run's own has no
 *    template;
 *  - `other-version`: same pipeline, another version picked by hand;
 *  - `other-pipeline`: a template for another pipeline than the run's;
 *  - `none`: the run was recognised but no template matches it. */
export type RunTemplateMatch = 'exact' | 'closest' | 'other-version' | 'other-pipeline' | 'none';

export interface RunTemplateMatchInput {
  /** Pipeline that made the run, e.g. `nf-core/ampliseq`. */
  runPipeline?: string | null;
  /** Pipeline version that made the run. */
  runVersion?: string | null;
  /** Template in use; null when none is chosen yet. */
  templateId?: string | null;
  /** The server's own verdict, for the template it chose. */
  detectedTemplateId?: string | null;
  detectedMatch?: 'exact' | 'closest' | 'none' | null;
}

/** The match between the run and the template in use; null when it cannot
 *  be told (the run was not recognised, or a version is unknown). */
export function runTemplateMatch(input: RunTemplateMatchInput): RunTemplateMatch | null {
  const { runPipeline, runVersion, templateId, detectedTemplateId, detectedMatch } = input;
  if (!templateId) {
    if (detectedMatch === 'none' || (runPipeline && !detectedTemplateId)) return 'none';
    return null;
  }
  const parts = splitTemplateId(templateId);
  if (runPipeline && runPipeline.toLowerCase() !== parts.pipeline.toLowerCase()) {
    return 'other-pipeline';
  }
  if (sameVersion(runVersion, parts.version)) return 'exact';
  if (detectedTemplateId && templateId === detectedTemplateId && detectedMatch) {
    return detectedMatch === 'none' ? null : detectedMatch;
  }
  if (runPipeline && runVersion && parts.version) return 'other-version';
  return null;
}

/** The words for a match: a short label for the badge and one sentence that
 *  spells the two versions out. */
export function runTemplateMatchText(
  match: RunTemplateMatch,
  versions: { run?: string | null; template?: string | null } = {},
): { label: string; detail: string } {
  const run = versions.run ? formatVersion(versions.run) : 'an unknown version';
  const template = versions.template ? formatVersion(versions.template) : 'an unknown version';
  switch (match) {
    case 'exact':
      return {
        label: 'Exact match',
        detail: `The template was written for ${template}, the pipeline version that made this run.`,
      };
    case 'closest':
      return {
        label: 'Closest available version',
        detail: `This run was made with ${run}. No template exists for it, so the closest one, written for ${template}, is used.`,
      };
    case 'other-version':
      return {
        label: 'Different version',
        detail: `This run was made with ${run}; the template you picked was written for ${template}.`,
      };
    case 'other-pipeline':
      return {
        label: 'Different pipeline',
        detail: 'The template you picked was written for another pipeline than the one that made this run.',
      };
    case 'none':
    default:
      return {
        label: 'No matching template',
        detail: 'No installed template matches the pipeline that made this run. Pick one yourself.',
      };
  }
}

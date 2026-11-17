/**
 * The browser's display settings as data: one registry entry per setting, each
 * naming the JBrowse state-tree actions that set it. Everything here is pure
 * (no React, no mobx): the hook in `useDisplaySettings.ts` owns persistence and
 * reactivity, the menu in `ViewMenu.tsx` draws the controls.
 *
 * The action names were read from the 4.3.0 sources of the linear-genome-view,
 * alignments, wiggle and variants plugins. A display type that lacks an action
 * (a single-sample variant track has no row height, a coverage track no arcs)
 * is skipped silently: an apply never throws.
 */

export type DisplayGroup = 'view' | 'alignments' | 'coverage' | 'features' | 'variants';

export type DisplayControl = 'switch' | 'segmented' | 'select' | 'number' | 'text';

export type DisplaySettingValue = string | number | boolean;

import type { JBrowseDisplaySettings } from '../../api';

export type { JBrowseDisplaySettings };

export type DisplaySettingKey = keyof JBrowseDisplaySettings;

/** A state-tree node (view, track or display), seen through its actions. */
export type Model = Record<string, unknown>;

export interface DisplaySettingOption {
  value: string;
  label: string;
}

export interface DisplaySettingEntry {
  key: DisplaySettingKey;
  group: DisplayGroup;
  label: string;
  control: DisplayControl;
  options?: DisplaySettingOption[];
  min?: number;
  max?: number;
  /** `'view'` for the linear genome view, else the display types it reaches. */
  target: 'view' | string[];
  /** What JBrowse does with no setting; only the view group has one, to
   *  neutralise the `lgv-*` localStorage values it leaks between tiles. */
  builtin?: DisplaySettingValue;
  /** The live value on this node, undefined when it cannot tell. */
  read: (model: Model) => DisplaySettingValue | undefined;
  /** `ctx` is every resolved setting, for the ones that depend on a sibling. */
  apply: (model: Model, value: DisplaySettingValue, ctx: JBrowseDisplaySettings) => void;
}

// ---- guarded access to state-tree nodes -------------------------------------

const asModel = (v: unknown): Model | null => (v && typeof v === 'object' ? (v as Model) : null);

/** Calls `model[name](...args)`; false when it is missing or throws. */
function call(model: Model, name: string, ...args: unknown[]): boolean {
  const fn = model[name];
  if (typeof fn !== 'function') return false;
  try {
    (fn as (...a: unknown[]) => unknown).apply(model, args);
    return true;
  } catch {
    return false;
  }
}

/** A getter that may be missing or throw (an unconfigured display). */
function get(model: Model | null, name: string): unknown {
  if (!model) return undefined;
  try {
    return model[name];
  } catch {
    return undefined;
  }
}

const child = (model: Model, name: string): Model | null => asModel(get(model, name));

/** The pileup (or arcs, or cloud) panel under an alignments wrapper. */
const pileupOf = (model: Model) => child(model, 'PileupDisplay');
const coverageOf = (model: Model) => child(model, 'SNPCoverageDisplay');

/**
 * Reach `want` through a toggle-only action. The toggles flip the stored
 * override rather than the effective value, so one flip can leave the setting
 * where it was (an override that is unset reads as the config's default):
 * flip at most twice, and only while the read disagrees.
 */
function toggleTo(model: Model, action: string, read: () => boolean, want: boolean): void {
  for (let i = 0; i < 2 && read() !== want; i += 1) {
    if (!call(model, action)) return;
  }
}

const bool = (v: unknown): boolean | undefined => (typeof v === 'boolean' ? v : undefined);
const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);
const num = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined;

const choices = (...pairs: Array<[string, string]>): DisplaySettingOption[] =>
  pairs.map(([value, label]) => ({ value, label }));

// ---- the registry -------------------------------------------------------------

const VIEW: 'view' = 'view';
const ALIGNMENTS = ['LinearAlignmentsDisplay'];
const WIGGLE = ['LinearWiggleDisplay', 'MultiLinearWiggleDisplay', 'LinearSNPCoverageDisplay'];
const FEATURES = ['LinearBasicDisplay', 'LinearFeatureDisplay'];
const VARIANTS = ['LinearVariantDisplay', 'MultiLinearVariantDisplay', 'LinearVariantMatrixDisplay'];

/** Pileup feature height and spacing per `read_height` (JBrowse's own presets). */
const READ_HEIGHTS: Record<string, [number, boolean]> = {
  normal: [7, false],
  compact: [2, true],
  super_compact: [1, true],
};

const LOWER_PANELS: Record<string, string> = {
  pileup: 'LinearPileupDisplay',
  arcs: 'LinearReadArcsDisplay',
  cloud: 'LinearReadCloudDisplay',
};

const FILLS: Record<string, number> = { filled: 0, line: 1, emphasis: 2 };

export const DISPLAY_SETTINGS: DisplaySettingEntry[] = [
  // view: defaults are the LinearGenomeView model's own
  {
    key: 'center_line',
    group: 'view',
    label: 'Center line',
    control: 'switch',
    target: VIEW,
    builtin: false,
    read: (m) => bool(get(m, 'showCenterLine')),
    apply: (m, v) => void call(m, 'setShowCenterLine', v),
  },
  {
    key: 'gridlines',
    group: 'view',
    label: 'Gridlines',
    control: 'switch',
    target: VIEW,
    builtin: true,
    read: (m) => bool(get(m, 'showGridlines')),
    apply: (m, v) => void call(m, 'setShowGridlines', v),
  },
  {
    key: 'cytobands',
    group: 'view',
    label: 'Cytobands',
    control: 'switch',
    target: VIEW,
    builtin: true,
    read: (m) => bool(get(m, 'showCytobandsSetting')),
    apply: (m, v) => void call(m, 'setShowCytobands', v),
  },
  {
    key: 'track_outlines',
    group: 'view',
    label: 'Track outlines',
    control: 'switch',
    target: VIEW,
    builtin: true,
    read: (m) => bool(get(m, 'showTrackOutlines')),
    apply: (m, v) => void call(m, 'setShowTrackOutlines', v),
  },
  {
    key: 'color_by_cds',
    group: 'view',
    label: 'Color by CDS',
    control: 'switch',
    target: VIEW,
    builtin: false,
    read: (m) => bool(get(m, 'colorByCDS')),
    apply: (m, v) => void call(m, 'setColorByCDS', v),
  },
  {
    key: 'track_labels',
    group: 'view',
    label: 'Track labels',
    control: 'segmented',
    options: choices(['overlapping', 'Overlap'], ['offset', 'Offset'], ['hidden', 'Hidden']),
    target: VIEW,
    builtin: 'overlapping',
    read: (m) => str(get(m, 'trackLabelsSetting')),
    apply: (m, v) => void call(m, 'setTrackLabels', v),
  },

  // alignments: the wrapper display, reaching its pileup and coverage panels
  {
    key: 'color_scheme',
    group: 'alignments',
    label: 'Color by',
    control: 'select',
    options: choices(
      ['normal', 'Normal'],
      ['mappingQuality', 'Mapping quality'],
      ['strand', 'Strand'],
      ['perBaseQuality', 'Base quality'],
      ['stranded', 'First-of-pair strand'],
      ['pairOrientation', 'Pair orientation'],
      ['insertSize', 'Insert size'],
      ['tag', 'Tag'],
      ['modifications', 'Modifications'],
      ['methylation', 'Methylation'],
    ),
    target: ALIGNMENTS,
    read: (m) => str(asModel(get(pileupOf(m), 'colorBy'))?.type),
    apply: (m, v, ctx) => {
      const pileup = pileupOf(m);
      if (!pileup) return;
      // A tag scheme without a tag has nothing to colour by.
      if (v === 'tag') {
        if (ctx.color_tag) call(pileup, 'setColorScheme', { type: 'tag', tag: ctx.color_tag });
        return;
      }
      call(pileup, 'setColorScheme', { type: v });
    },
  },
  {
    key: 'color_tag',
    group: 'alignments',
    label: 'Tag',
    control: 'text',
    target: ALIGNMENTS,
    read: (m) => str(asModel(get(pileupOf(m), 'colorBy'))?.tag),
    apply: (m, v, ctx) => {
      // The tag only means something with the tag scheme: re-apply it.
      if (ctx.color_scheme !== 'tag' || typeof v !== 'string' || !v) return;
      const pileup = pileupOf(m);
      if (pileup) call(pileup, 'setColorScheme', { type: 'tag', tag: v });
    },
  },
  {
    key: 'soft_clipping',
    group: 'alignments',
    label: 'Soft clipping',
    control: 'switch',
    target: ALIGNMENTS,
    read: (m) => bool(get(pileupOf(m), 'showSoftClipping')),
    apply: (m, v) => {
      const pileup = pileupOf(m);
      if (pileup) toggleTo(pileup, 'toggleSoftClipping', () => !!get(pileup, 'showSoftClipping'), !!v);
    },
  },
  {
    key: 'mismatch_alpha',
    group: 'alignments',
    label: 'Fade low-quality mismatches',
    control: 'switch',
    target: ALIGNMENTS,
    read: (m) => bool(get(pileupOf(m), 'mismatchAlphaSetting')),
    apply: (m, v) => {
      const pileup = pileupOf(m);
      if (pileup) {
        toggleTo(pileup, 'toggleMismatchAlpha', () => !!get(pileup, 'mismatchAlphaSetting'), !!v);
      }
    },
  },
  {
    key: 'read_height',
    group: 'alignments',
    label: 'Read height',
    control: 'segmented',
    options: choices(['normal', 'Normal'], ['compact', 'Compact'], ['super_compact', 'Dense']),
    target: ALIGNMENTS,
    read: (m) => {
      const pileup = pileupOf(m);
      if (!pileup) return undefined;
      const spaced = get(pileup, 'noSpacingSetting') !== true;
      const height = get(pileup, 'featureHeightSetting');
      if (!spaced && height === 1) return 'super_compact';
      if (!spaced && height === 2) return 'compact';
      return 'normal';
    },
    apply: (m, v) => {
      const pileup = pileupOf(m);
      const preset = READ_HEIGHTS[String(v)];
      if (!pileup || !preset) return;
      call(pileup, 'setFeatureHeight', preset[0]);
      call(pileup, 'setNoSpacing', preset[1]);
    },
  },
  {
    key: 'hide_small_indels',
    group: 'alignments',
    label: 'Hide small indels',
    control: 'switch',
    target: ALIGNMENTS,
    read: (m) => bool(get(pileupOf(m), 'hideSmallIndels')),
    apply: (m, v) => {
      const pileup = pileupOf(m);
      if (pileup) call(pileup, 'setHideSmallIndels', !!v);
    },
  },
  {
    key: 'hide_mismatches',
    group: 'alignments',
    label: 'Hide mismatches',
    control: 'switch',
    target: ALIGNMENTS,
    read: (m) => bool(get(pileupOf(m), 'hideMismatches')),
    apply: (m, v) => {
      const pileup = pileupOf(m);
      if (pileup) call(pileup, 'setHideMismatches', !!v);
    },
  },
  {
    key: 'lower_panel',
    group: 'alignments',
    label: 'Lower panel',
    control: 'segmented',
    options: choices(['pileup', 'Pileup'], ['arcs', 'Arcs'], ['cloud', 'Cloud']),
    target: ALIGNMENTS,
    read: (m) => {
      const type = str(get(m, 'lowerPanelType'));
      return Object.keys(LOWER_PANELS).find((k) => LOWER_PANELS[k] === type);
    },
    apply: (m, v) => {
      const type = LOWER_PANELS[String(v)];
      if (type) call(m, 'setLowerPanelType', type);
    },
  },
  {
    key: 'coverage_height',
    group: 'alignments',
    label: 'Coverage height',
    control: 'number',
    min: 20,
    max: 2000,
    target: ALIGNMENTS,
    read: (m) => num(get(m, 'snpCovHeight')),
    apply: (m, v) => {
      call(m, 'setSNPCoverageHeight', v);
      // The wrapper mirrors the coverage panel's own height back into
      // `snpCovHeight`, so the panel has to move too or it undoes the change.
      const cov = coverageOf(m);
      if (cov) call(cov, 'setHeight', v);
    },
  },
  {
    key: 'sashimi_arcs',
    group: 'alignments',
    label: 'Splice junction arcs',
    control: 'switch',
    target: ALIGNMENTS,
    read: (m) => bool(get(coverageOf(m), 'showArcsSetting')),
    apply: (m, v) => {
      const cov = coverageOf(m);
      if (cov) call(cov, 'setShowArcs', !!v);
    },
  },
  {
    key: 'min_arc_score',
    group: 'alignments',
    label: 'Min arc score',
    control: 'number',
    min: 0,
    max: 10000,
    target: ALIGNMENTS,
    read: (m) => num(get(coverageOf(m), 'minArcScore')),
    apply: (m, v) => {
      const cov = coverageOf(m);
      if (cov) call(cov, 'setMinArcScore', v);
    },
  },

  // coverage: wiggle tracks and the SNP coverage panel (a wiggle display)
  {
    key: 'scale',
    group: 'coverage',
    label: 'Scale',
    control: 'segmented',
    options: choices(['linear', 'Linear'], ['log', 'Log']),
    target: WIGGLE,
    read: (m) => str(get(m, 'scaleType')),
    apply: (m, v) => void call(m, 'setScaleType', v),
  },
  {
    key: 'autoscale',
    group: 'coverage',
    label: 'Autoscale',
    control: 'segmented',
    options: choices(
      ['local', 'Local'],
      ['global', 'Global'],
      ['globalsd', 'Global SD'],
      ['localsd', 'Local SD'],
    ),
    target: WIGGLE,
    read: (m) => str(get(m, 'autoscaleType')),
    apply: (m, v) => void call(m, 'setAutoscale', v),
  },
  {
    // Across tracks rather than on one, so `useSharedScale.ts` applies it: a
    // per-display apply cannot see the other tracks' ranges.
    key: 'y_scale',
    group: 'coverage',
    label: 'Y scale',
    control: 'segmented',
    options: choices(['per_track', 'Per track'], ['shared', 'Shared']),
    target: WIGGLE,
    read: () => 'per_track',
    apply: () => undefined,
  },
  {
    key: 'renderer',
    group: 'coverage',
    label: 'Style',
    control: 'segmented',
    options: choices(['xyplot', 'XY plot'], ['density', 'Density'], ['line', 'Line']),
    target: WIGGLE,
    read: (m) => str(get(m, 'rendererTypeNameState')),
    apply: (m, v) => {
      // The SNP coverage panel draws with its own renderer, which this would
      // only shadow.
      if (get(m, 'type') === 'LinearSNPCoverageDisplay') return;
      call(m, 'setRendererType', v);
    },
  },
  {
    key: 'fill',
    group: 'coverage',
    label: 'Fill',
    control: 'segmented',
    options: choices(['filled', 'Filled'], ['line', 'Line'], ['emphasis', 'Bold line']),
    target: WIGGLE,
    read: () => undefined,
    apply: (m, v) => {
      const code = FILLS[String(v)];
      // Only the XY plot renderer has a fill.
      if (code !== undefined && get(m, 'canHaveFill') === true) call(m, 'setFill', code);
    },
  },
  {
    key: 'summary',
    group: 'coverage',
    label: 'Summary',
    control: 'segmented',
    options: choices(['min', 'Min'], ['max', 'Max'], ['avg', 'Mean'], ['whiskers', 'Whiskers']),
    target: WIGGLE,
    read: (m) => str(get(m, 'summaryScoreModeSetting')),
    apply: (m, v) => {
      if (get(m, 'hasResolution') === true) call(m, 'setSummaryScoreMode', v);
    },
  },

  // features
  {
    key: 'feature_mode',
    group: 'features',
    label: 'Display mode',
    control: 'segmented',
    options: choices(
      ['normal', 'Normal'],
      ['compact', 'Compact'],
      ['reducedRepresentation', 'Reduced'],
      ['collapse', 'Collapse'],
    ),
    target: FEATURES,
    read: (m) => str(get(m, 'displayMode')),
    apply: (m, v) => void call(m, 'setDisplayMode', v),
  },
  {
    key: 'feature_labels',
    group: 'features',
    label: 'Feature labels',
    control: 'switch',
    target: FEATURES,
    read: (m) => bool(get(m, 'showLabels')),
    apply: (m, v) => toggleTo(m, 'toggleShowLabels', () => !!get(m, 'showLabels'), !!v),
  },
  {
    key: 'feature_descriptions',
    group: 'features',
    label: 'Descriptions',
    control: 'switch',
    target: FEATURES,
    read: (m) => bool(get(m, 'showDescriptions')),
    apply: (m, v) =>
      toggleTo(m, 'toggleShowDescriptions', () => !!get(m, 'showDescriptions'), !!v),
  },
  {
    key: 'gene_glyph',
    group: 'features',
    label: 'Gene glyph',
    control: 'segmented',
    options: choices(['all', 'All'], ['longest', 'Longest'], ['longestCoding', 'Longest coding']),
    target: FEATURES,
    read: (m) => str(get(m, 'geneGlyphMode')),
    apply: (m, v) => void call(m, 'setGeneGlyphMode', v),
  },

  // variants
  {
    key: 'variant_row_height',
    group: 'variants',
    label: 'Row height',
    control: 'number',
    min: 1,
    max: 50,
    target: VARIANTS,
    // `rowHeightMode` is 'auto' or a number; auto has no number to show.
    read: (m) => num(get(m, 'rowHeightMode')),
    apply: (m, v) => void call(m, 'setRowHeight', v),
  },
  {
    key: 'phased',
    group: 'variants',
    label: 'Phased genotypes',
    control: 'switch',
    target: VARIANTS,
    read: (m) => {
      const mode = str(get(m, 'renderingModeSetting'));
      return mode === undefined ? undefined : mode === 'phased';
    },
    apply: (m, v) => void call(m, 'setPhasedMode', v ? 'phased' : 'alleleCount'),
  },
];

const ENTRY_BY_KEY = new Map<string, DisplaySettingEntry>(DISPLAY_SETTINGS.map((e) => [e.key, e]));

export const GROUP_ORDER: DisplayGroup[] = ['view', 'alignments', 'coverage', 'features', 'variants'];

export const GROUP_LABELS: Record<DisplayGroup, string> = {
  view: 'View',
  alignments: 'Alignments',
  coverage: 'Coverage',
  features: 'Features',
  variants: 'Variants',
};

/** Settings another one's apply depends on: re-applied after it. */
const DEPENDENTS: Partial<Record<DisplaySettingKey, DisplaySettingKey[]>> = {
  // A fill exists only on the XY plot renderer.
  renderer: ['fill'],
};

export const entryFor = (key: DisplaySettingKey): DisplaySettingEntry | undefined =>
  ENTRY_BY_KEY.get(key);

export const entriesFor = (group: DisplayGroup): DisplaySettingEntry[] =>
  DISPLAY_SETTINGS.filter((e) => e.group === group);

// ---- pure helpers -----------------------------------------------------------

/** local (this tile's stored choice) over YAML over nothing (JBrowse's default). */
export function resolveValue(
  key: DisplaySettingKey,
  local: JBrowseDisplaySettings | null | undefined,
  yaml: JBrowseDisplaySettings | null | undefined,
): DisplaySettingValue | undefined {
  const fromLocal = local?.[key];
  if (fromLocal !== undefined && fromLocal !== null) return fromLocal;
  const fromYaml = yaml?.[key];
  if (fromYaml !== undefined && fromYaml !== null) return fromYaml;
  return undefined;
}

/** Every setting with a value (numbers clamped): local, else YAML, else the view group's built-in. */
export function resolveAll(
  local: JBrowseDisplaySettings | null | undefined,
  yaml: JBrowseDisplaySettings | null | undefined,
): JBrowseDisplaySettings {
  const out: Record<string, DisplaySettingValue> = {};
  for (const entry of DISPLAY_SETTINGS) {
    const value = resolveValue(entry.key, local, yaml) ?? entry.builtin;
    if (value !== undefined) out[entry.key] = clampValue(entry, value);
  }
  return out as JBrowseDisplaySettings;
}

/** A number held inside the entry's bounds (any other value as it is). */
export function clampValue(entry: DisplaySettingEntry, value: DisplaySettingValue): DisplaySettingValue {
  if (entry.control !== 'number' || typeof value !== 'number') return value;
  return Math.min(entry.max ?? Infinity, Math.max(entry.min ?? -Infinity, value));
}

/**
 * A stored or typed value the control could have produced, else undefined:
 * the right type, an offered option, a number clamped into its bounds.
 */
export function sanitizeValue(
  entry: DisplaySettingEntry,
  value: unknown,
): DisplaySettingValue | undefined {
  switch (entry.control) {
    case 'switch':
      return typeof value === 'boolean' ? value : undefined;
    case 'segmented':
    case 'select':
      return typeof value === 'string' && entry.options?.some((o) => o.value === value)
        ? value
        : undefined;
    case 'number':
      return typeof value === 'number' && Number.isFinite(value)
        ? clampValue(entry, value)
        : undefined;
    case 'text':
      return typeof value === 'string' ? value.trim() : undefined;
    default:
      return undefined;
  }
}

/** A display plus the panels an alignments wrapper holds, which are displays too. */
function expand(display: Model): Model[] {
  const parts = [display];
  for (const name of ['SNPCoverageDisplay', 'PileupDisplay']) {
    const part = child(display, name);
    if (part) parts.push(part);
  }
  return parts;
}

/** Every display of every open track, wrapper panels included. */
function allDisplays(view: Model): Model[] {
  const tracks = get(view, 'tracks');
  if (!Array.isArray(tracks)) return [];
  const out: Model[] = [];
  for (const track of tracks) {
    const displays = get(asModel(track), 'displays');
    if (!Array.isArray(displays)) continue;
    for (const display of displays) {
      const model = asModel(display);
      if (model) out.push(...expand(model));
    }
  }
  return out;
}

/** The nodes an entry applies to: the view, or the open displays of its types. */
export function displaysOf(view: unknown, entry: DisplaySettingEntry): Model[] {
  const root = asModel(view);
  if (!root) return [];
  if (entry.target === 'view') return [root];
  const wanted = entry.target;
  return allDisplays(root).filter((d) => {
    const type = get(d, 'type');
    return typeof type === 'string' && wanted.includes(type);
  });
}

/** A track's name, from its configuration slot (a plain string in tests). */
function trackName(track: Model): string | null {
  const conf = asModel(get(track, 'configuration'));
  const slot = conf ? get(conf, 'name') : undefined;
  const value = typeof slot === 'string' ? slot : get(asModel(slot), 'value');
  if (typeof value === 'string' && value) return value;
  const id = conf ? get(conf, 'trackId') : undefined;
  return typeof id === 'string' ? id : null;
}

/**
 * The names of the open tracks a group's settings act on, in track order:
 * the panel says it under the group's title, so "Display mode" is not read as
 * acting on the signal tracks. Empty for the view group.
 */
export function groupTrackNames(view: unknown, group: DisplayGroup): string[] {
  const root = asModel(view);
  if (!root || group === 'view') return [];
  const types = new Set(entriesFor(group).flatMap((e) => (e.target === 'view' ? [] : e.target)));
  const tracks = get(root, 'tracks');
  if (!Array.isArray(tracks)) return [];
  const names: string[] = [];
  for (const t of tracks) {
    const track = asModel(t);
    const displays = track ? get(track, 'displays') : undefined;
    if (!track || !Array.isArray(displays)) continue;
    const hit = displays.some((d) => {
      const model = asModel(d);
      return !!model && expand(model).some((m) => types.has(String(get(m, 'type'))));
    });
    const name = hit ? trackName(track) : null;
    if (name) names.push(name);
  }
  return names;
}

/** The types of every open display (an alignments wrapper and its panels). */
export function openDisplayTypes(view: unknown): string[] {
  const root = asModel(view);
  if (!root) return [];
  const types = new Set<string>();
  for (const d of allDisplays(root)) {
    const type = get(d, 'type');
    if (typeof type === 'string') types.add(type);
  }
  return [...types];
}

/** The groups worth showing: the view's always, the rest with a display open. */
export function groupsFor(openTypes: Iterable<string>): DisplayGroup[] {
  const open = new Set(openTypes);
  return GROUP_ORDER.filter(
    (group) =>
      group === 'view' ||
      entriesFor(group).some(
        (e) => e.target !== 'view' && e.target.some((type) => open.has(type)),
      ),
  );
}

/**
 * An identity for a display that changes when it is replaced: a lower-panel
 * switch swaps the pileup for an arcs display under the same wrapper, and the
 * new panel needs the settings again.
 */
export function displayKey(display: Model): string {
  const self = `${String(get(display, 'type'))}:${String(get(display, 'id') ?? '')}`;
  const parts = ['SNPCoverageDisplay', 'PileupDisplay']
    .map((name) => child(display, name))
    .filter((p): p is Model => p !== null)
    .map((p) => `${String(get(p, 'type'))}:${String(get(p, 'id') ?? '')}`);
  return parts.length ? `${self}|${parts.join('|')}` : self;
}

/** Keys of every open display, for a reaction to watch. */
export function displayKeys(view: unknown): string[] {
  const root = asModel(view);
  return root ? allDisplays(root).map(displayKey) : [];
}

/**
 * What a node read before the first time a setting was applied to it. Reset
 * puts that back for a setting the YAML says nothing about, since JBrowse has no
 * "unset" for most of these.
 */
export type Baselines = WeakMap<object, Map<DisplaySettingKey, DisplaySettingValue | undefined>>;

function remember(baselines: Baselines | undefined, node: Model, entry: DisplaySettingEntry) {
  if (!baselines) return;
  let seen = baselines.get(node);
  if (!seen) {
    seen = new Map();
    baselines.set(node, seen);
  }
  if (seen.has(entry.key)) return;
  try {
    seen.set(entry.key, entry.read(node));
  } catch {
    seen.set(entry.key, undefined);
  }
}

/** Apply one setting to every matching node; `only` narrows to given nodes' keys. */
export function applySetting(
  view: unknown,
  entry: DisplaySettingEntry,
  value: DisplaySettingValue,
  ctx: JBrowseDisplaySettings,
  opts?: { baselines?: Baselines; only?: Set<string> },
): void {
  // `only` is a set of display keys: the view is not one of them.
  if (opts?.only && entry.target === 'view') return;
  for (const node of displaysOf(view, entry)) {
    if (opts?.only && !opts.only.has(displayKey(node))) continue;
    remember(opts?.baselines, node, entry);
    try {
      entry.apply(node, value, ctx);
    } catch {
      // A display in a state the action cannot take: leave it as it is.
    }
  }
}

/** Apply every resolved setting, then the ones that depend on another. */
export function applyAll(
  view: unknown,
  resolved: JBrowseDisplaySettings,
  opts?: { baselines?: Baselines; only?: Set<string> },
): void {
  for (const entry of DISPLAY_SETTINGS) {
    const value = resolved[entry.key];
    if (value === undefined) continue;
    applySetting(view, entry, value, resolved, opts);
  }
}

/** One setting changed: apply it, then whatever depends on it. */
export function applyOne(
  view: unknown,
  key: DisplaySettingKey,
  resolved: JBrowseDisplaySettings,
  opts?: { baselines?: Baselines },
): void {
  const keys = [key, ...(DEPENDENTS[key] ?? [])];
  for (const k of keys) {
    const entry = ENTRY_BY_KEY.get(k);
    const value = resolved[k];
    if (entry && value !== undefined) applySetting(view, entry, value, resolved, opts);
  }
}

/** Put a setting back to what each node read before it was first applied. */
export function restoreBaseline(
  view: unknown,
  entry: DisplaySettingEntry,
  baselines: Baselines,
  ctx: JBrowseDisplaySettings,
): void {
  for (const node of displaysOf(view, entry)) {
    const before = baselines.get(node)?.get(entry.key);
    if (before === undefined) continue;
    try {
      entry.apply(node, before, ctx);
    } catch {
      // see applySetting
    }
  }
}

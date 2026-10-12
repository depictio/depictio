/**
 * NGFF 0.4 metadata to viewer state: axis sizes, per-channel defaults and the
 * physical pixel size. Pure (no viv / deck import) so it runs in vitest and
 * stays off the renderer's eager path.
 */

/** viv shades at most this many channels at once (its `MAX_CHANNELS`). */
export const MAX_RENDERED_CHANNELS = 6;

/** Additive fluorescence LUTs for channels with no colour of their own
 *  (blue, green, red, magenta, cyan, yellow). Channels are summed on a black
 *  field, so these are the domain convention, not UI colours, and are
 *  deliberately not themed. A single channel reads as greyscale. */
const FLUORESCENCE_COLORS = ['#0000ff', '#00ff00', '#ff0000', '#ff00ff', '#00ffff', '#ffff00'];
const GREYSCALE = '#ffffff';

export type Rgb = [number, number, number];

/** `#rrggbb`, `rrggbb` (OMERO's spelling) or `#rgb` to RGB, else null. */
export function hexToRgb(hex: string | null | undefined): Rgb | null {
  if (typeof hex !== 'string') return null;
  let h = hex.trim().replace(/^#/, '');
  if (/^[0-9a-f]{3}$/i.test(h)) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('');
  }
  if (!/^[0-9a-f]{6}$/i.test(h)) return null;
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
}

/** Normalise any accepted hex spelling to `#rrggbb`, else null. */
export function normaliseHex(hex: string | null | undefined): string | null {
  const rgb = hexToRgb(hex);
  return rgb ? `#${rgb.map((v) => v.toString(16).padStart(2, '0')).join('')}` : null;
}

export function defaultChannelColor(index: number, count: number): string {
  return count <= 1 ? GREYSCALE : FLUORESCENCE_COLORS[index % FLUORESCENCE_COLORS.length];
}

/** Full value range of an integer dtype (viv's spelling: `Uint16`, ...), or
 *  null for floats, whose range has to come from the data. */
export function dtypeRange(dtype: string): [number, number] | null {
  switch (dtype) {
    case 'Uint8':
      return [0, 255];
    case 'Uint16':
      return [0, 65535];
    case 'Uint32':
      return [0, 4294967295];
    case 'Int8':
      return [-128, 127];
    case 'Int16':
      return [-32768, 32767];
    case 'Int32':
      return [-2147483648, 2147483647];
    default:
      return null;
  }
}

/** Sizes of the non-spatial axes; an absent axis counts as size 1. */
export function axisSizes(
  labels: readonly string[],
  shape: readonly number[],
): { c: number; z: number; t: number } {
  const size = (name: string) => {
    const i = labels.indexOf(name);
    return i >= 0 ? (shape[i] ?? 1) : 1;
  };
  return { c: size('c'), z: size('z'), t: size('t') };
}

/** A viv selection for one channel, naming only the axes the array has
 *  (viv's indexer throws on a key it does not know). */
export function selectionFor(
  labels: readonly string[],
  sel: { c: number; z: number; t: number },
): Record<string, number> {
  const out: Record<string, number> = {};
  if (labels.includes('c')) out.c = sel.c;
  if (labels.includes('z')) out.z = sel.z;
  if (labels.includes('t')) out.t = sel.t;
  return out;
}

/** What the viewer draws for one channel. `color` is `#rrggbb`. */
export interface ChannelState {
  index: number;
  name: string;
  color: string;
  visible: boolean;
  contrastLimits: [number, number];
  /** Slider bounds for the contrast limits. */
  domain: [number, number];
}

/** A channel entry of the component config (`BioimageChannel`). */
export interface ConfigChannel {
  index: number;
  name?: string | null;
  visible?: boolean;
  color?: string | null;
  contrast_limits?: [number, number] | null;
}

interface OmeroChannel {
  label?: string;
  color?: string;
  active?: boolean;
  window?: { start?: number; end?: number; min?: number; max?: number };
}

/** Per-channel intensity statistics, as viv's `getChannelStats` reports them. */
export interface ChannelStats {
  domain: [number, number];
  contrastLimits: [number, number];
}

function finitePair(a: unknown, b: unknown): [number, number] | null {
  return typeof a === 'number' && typeof b === 'number' && Number.isFinite(a) && Number.isFinite(b)
    ? [a, b]
    : null;
}

/**
 * The starting state of every channel.
 *
 * Each field is taken from the first source that has it: the component config
 * (what the dashboard author pinned), then the store's own `omero` rendering
 * settings, then the data (`stats`, from the lowest pyramid level), then the
 * dtype. Only the first `MAX_RENDERED_CHANNELS` channels start visible unless
 * config or omero say otherwise, since viv cannot shade more at once.
 */
export function resolveChannels(opts: {
  sizeC: number;
  dtype: string;
  omero?: { channels?: OmeroChannel[] } | null;
  config?: readonly ConfigChannel[] | null;
  stats?: ReadonlyArray<ChannelStats | null | undefined>;
}): ChannelState[] {
  const { sizeC, dtype, omero, config, stats } = opts;
  const byIndex = new Map<number, ConfigChannel>();
  for (const c of config ?? []) if (typeof c?.index === 'number') byIndex.set(c.index, c);
  const range = dtypeRange(dtype);
  const out: ChannelState[] = [];
  for (let i = 0; i < sizeC; i += 1) {
    const cfg = byIndex.get(i);
    const om = omero?.channels?.[i];
    const st = stats?.[i] ?? null;
    const domain: [number, number] =
      st?.domain ?? finitePair(om?.window?.min, om?.window?.max) ?? range ?? [0, 1];
    const contrastLimits: [number, number] =
      finitePair(cfg?.contrast_limits?.[0], cfg?.contrast_limits?.[1]) ??
      finitePair(om?.window?.start, om?.window?.end) ??
      st?.contrastLimits ?? [domain[0], domain[1]];
    out.push({
      index: i,
      name: cfg?.name || om?.label || `Channel ${i}`,
      color:
        normaliseHex(cfg?.color) ?? normaliseHex(om?.color) ?? defaultChannelColor(i, sizeC),
      visible: cfg?.visible ?? om?.active ?? i < MAX_RENDERED_CHANNELS,
      contrastLimits,
      // Widen the slider to whatever the limits already span, so a pinned
      // window outside the observed data range is still reachable.
      domain: [Math.min(domain[0], contrastLimits[0]), Math.max(domain[1], contrastLimits[1])],
    });
  }
  return out;
}

/** The channels handed to viv: the visible ones, capped at what it can shade.
 *  An all-hidden image still needs one channel for the layer to exist, drawn
 *  invisible. */
export function renderedChannels(channels: readonly ChannelState[]): ChannelState[] {
  const visible = channels.filter((c) => c.visible).slice(0, MAX_RENDERED_CHANNELS);
  if (visible.length) return visible;
  return channels.length ? [{ ...channels[0], visible: false }] : [];
}

const UNIT_ABBREVIATIONS: Record<string, string> = {
  angstrom: 'Å',
  nanometer: 'nm',
  micrometer: 'µm',
  micron: 'µm',
  millimeter: 'mm',
  centimeter: 'cm',
  meter: 'm',
};

export function abbreviateUnit(unit: string): string {
  return UNIT_ABBREVIATIONS[unit.toLowerCase()] ?? unit;
}

interface NgffMultiscale {
  axes?: Array<{ name?: string; unit?: string } | string>;
  datasets?: Array<{ coordinateTransformations?: Array<{ type?: string; scale?: number[] }> }>;
  coordinateTransformations?: Array<{ type?: string; scale?: number[] }>;
}

function scaleOf(transforms: NgffMultiscale['coordinateTransformations']): number[] | null {
  const t = (transforms ?? []).find((x) => x?.type === 'scale' && Array.isArray(x.scale));
  return t?.scale ?? null;
}

/**
 * Size of one level-0 pixel along x, with its unit, from the NGFF 0.4
 * multiscale: the x axis' `unit` and the first dataset's `scale` (times the
 * multiscale-level `scale`, when there is one). Null when x has no unit,
 * because a bar labelled in pixels says nothing the image does not.
 */
export function physicalPixelSize(
  rootAttrs: { multiscales?: NgffMultiscale[] } | null | undefined,
): { value: number; unit: string } | null {
  const ms = rootAttrs?.multiscales?.[0];
  if (!ms?.axes) return null;
  const xIndex = ms.axes.findIndex((a) => (typeof a === 'string' ? a : a?.name) === 'x');
  if (xIndex < 0) return null;
  const axis = ms.axes[xIndex];
  const unit = typeof axis === 'string' ? undefined : axis?.unit;
  if (!unit) return null;
  const datasetScale = scaleOf(ms.datasets?.[0]?.coordinateTransformations);
  const globalScale = scaleOf(ms.coordinateTransformations);
  const value = (datasetScale?.[xIndex] ?? 1) * (globalScale?.[xIndex] ?? 1);
  if (!(value > 0) || !Number.isFinite(value)) return null;
  return { value, unit: abbreviateUnit(unit) };
}

/** `1500 µm` style label, trimming float noise. */
export function formatLength(value: number, unit: string): string {
  const text = Number(value.toPrecision(3)).toString();
  return `${text} ${unit}`;
}

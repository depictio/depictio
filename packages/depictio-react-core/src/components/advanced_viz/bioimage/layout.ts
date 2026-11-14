// How an OME-Zarr store is laid out above its images: a single image, an HCS
// plate (plate → wells → fields), a bioformats2raw container (series `0`, `1`,
// ...), and the `labels/` group an image may carry. The viewer opens one image
// at a time, so all this has to do is find the group that image lives in and
// hand the image reader a store rooted there (`subStore`).
//
// NGFF 0.4 keeps a group's metadata in `.zattrs`; 0.5 (zarr v3) in
// `zarr.json`, under `attributes.ome`. Both are read, 0.5 first.

import type { BioimageZarrStore } from '../../../api';

export type NgffContainerLayout = 'image' | 'plate' | 'well' | 'bioformats2raw' | 'unknown';

export interface PlateWell {
  /** The well's group, relative to the plate root (`A/1`). */
  path: string;
  /** Row and column joined, normalised (`A1`): what a well filter matches. */
  name: string;
  row: string;
  column: string;
}

export interface NgffContainer {
  layout: NgffContainerLayout;
  version: string | null;
  /** The plate's wells, in the order the plate lists them. Empty otherwise. */
  wells: PlateWell[];
}

type Attrs = Record<string, unknown>;

const decoder = new TextDecoder();

function isRecord(v: unknown): v is Attrs {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** The store seen from inside the group at `prefix` (no leading or trailing
 *  slash). Composes: a well's sub-store, then its field's. */
export function subStore(store: BioimageZarrStore, prefix: string): BioimageZarrStore {
  const clean = prefix.replace(/^\/+|\/+$/g, '');
  if (!clean) return store;
  const at = (key: string) => `${clean}/${key.replace(/^\/+/, '')}`;
  return {
    get: (key, opts) => store.get(at(key), opts),
    getRange: (key, range, opts) => store.getRange(at(key), range, opts),
  };
}

async function readJson(store: BioimageZarrStore, key: string): Promise<Attrs | null> {
  const bytes = await store.get(key);
  if (!bytes) return null;
  try {
    const parsed: unknown = JSON.parse(decoder.decode(bytes));
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** The NGFF attributes of the group at `path` (`''` for the root): the `ome`
 *  block of a 0.5 group, the root attributes of a 0.4 one; null when the group
 *  has neither file. */
export async function readNgffAttrs(store: BioimageZarrStore, path = ''): Promise<Attrs | null> {
  const prefix = path ? `${path.replace(/\/+$/, '')}/` : '';
  const v3 = await readJson(store, `${prefix}zarr.json`);
  if (v3) {
    const attributes = isRecord(v3.attributes) ? v3.attributes : {};
    return isRecord(attributes.ome) ? attributes.ome : attributes;
  }
  return readJson(store, `${prefix}.zattrs`);
}

function versionOf(attrs: Attrs): string | null {
  if (attrs.version != null) return String(attrs.version);
  for (const key of ['multiscales', 'plate', 'well']) {
    let block = attrs[key];
    if (Array.isArray(block)) block = block[0];
    if (isRecord(block) && block.version != null) return String(block.version);
  }
  return null;
}

/** A well name as a filter value, a plate path or a table column may spell it
 *  (`A01`, `a/1`, `B_12`), reduced to letters then the column number (`A1`). A
 *  name that is not a row and a number is kept, upper-cased. */
export function normaliseWellName(raw: string): string {
  const text = String(raw).trim();
  const m = /^([A-Za-z]+)[\s/_-]*0*(\d+)$/.exec(text);
  return m ? `${m[1].toUpperCase()}${Number(m[2])}` : text.toUpperCase();
}

/** The wells of a `plate` block, named by the row and column their indices
 *  point at, else by their path (`C/7`). */
export function plateWells(plate: unknown): PlateWell[] {
  if (!isRecord(plate) || !Array.isArray(plate.wells)) return [];
  const names = (key: 'rows' | 'columns'): string[] =>
    Array.isArray(plate[key])
      ? (plate[key] as unknown[]).map((r) => (isRecord(r) && r.name != null ? String(r.name) : ''))
      : [];
  const rows = names('rows');
  const columns = names('columns');
  const out: PlateWell[] = [];
  for (const well of plate.wells as unknown[]) {
    if (!isRecord(well) || typeof well.path !== 'string') continue;
    const [pathRow = '', pathColumn = ''] = well.path.split('/');
    const row = (typeof well.rowIndex === 'number' && rows[well.rowIndex]) || pathRow;
    const column =
      (typeof well.columnIndex === 'number' && columns[well.columnIndex]) || pathColumn;
    out.push({ path: well.path, name: normaliseWellName(`${row}${column}`), row, column });
  }
  return out;
}

/** The well a filter value names, in any spelling, or null. */
export function wellForValue(wells: readonly PlateWell[], value: string): PlateWell | null {
  const wanted = normaliseWellName(value);
  return wells.find((w) => w.name === wanted || w.path === value) ?? null;
}

/** What the store's root is. Never throws on a missing file: a root with no
 *  metadata is `unknown`, and the image reader then says why it cannot open it. */
export async function openContainer(store: BioimageZarrStore): Promise<NgffContainer> {
  const attrs = await readNgffAttrs(store);
  if (!attrs) return { layout: 'unknown', version: null, wells: [] };
  const version = versionOf(attrs);
  if ('multiscales' in attrs) return { layout: 'image', version, wells: [] };
  if (isRecord(attrs.plate)) return { layout: 'plate', version, wells: plateWells(attrs.plate) };
  if ('well' in attrs) return { layout: 'well', version, wells: [] };
  if ('bioformats2raw.layout' in attrs) return { layout: 'bioformats2raw', version, wells: [] };
  return { layout: 'unknown', version, wells: [] };
}

/** The image group of field `field` of the well at `wellPath` (or of the
 *  root when it is a well itself, `wellPath` empty). */
export async function wellImagePath(
  store: BioimageZarrStore,
  wellPath: string,
  field = 0,
): Promise<string> {
  const attrs = await readNgffAttrs(store, wellPath);
  const well = attrs && isRecord(attrs.well) ? attrs.well : null;
  const images = well && Array.isArray(well.images) ? (well.images as unknown[]) : [];
  const image = images[field];
  const where = wellPath || 'root';
  if (!isRecord(image) || typeof image.path !== 'string') {
    throw new Error(
      images.length === 0 ? `Well ${where} lists no images` : `Well ${where} has no field ${field}`,
    );
  }
  return wellPath ? `${wellPath}/${image.path}` : image.path;
}

/** The image group under a container root: a well's first field, a
 *  bioformats2raw container's first series (listed in `OME`, else `0`); `''` when the root is the image. */
export async function containerImagePath(
  store: BioimageZarrStore,
  container: NgffContainer,
  wellPath: string | null,
): Promise<string> {
  switch (container.layout) {
    case 'plate': {
      const path = wellPath ?? container.wells[0]?.path;
      if (!path) throw new Error('This plate lists no wells');
      return wellImagePath(store, path);
    }
    case 'well':
      return wellImagePath(store, '');
    case 'bioformats2raw': {
      // The OME group may name the series (`setup0/timepoint0`); without a
      // list they are numbered from 0.
      const ome = await readNgffAttrs(store, 'OME');
      const series = ome && Array.isArray(ome.series) ? ome.series[0] : null;
      return typeof series === 'string' && series ? series.replace(/^\/+|\/+$/g, '') : '0';
    }
    default:
      return '';
  }
}

/** The group of the first label image an image carries (`labels/<name>`, the
 *  name its `labels/` group lists), or null when it has none. */
export async function firstLabelPath(store: BioimageZarrStore): Promise<string | null> {
  const attrs = await readNgffAttrs(store, 'labels');
  const names = attrs?.labels;
  if (!Array.isArray(names)) return null;
  const first = names.find((n): n is string => typeof n === 'string' && n.length > 0);
  return first ? `labels/${first}` : null;
}

/** The axis names the viewer draws (NGFF's own: time, channel, then space). */
const VIEWER_AXES = new Set(['t', 'c', 'z', 'y', 'x']);

/** Why the viewer cannot draw the image whose attributes are `attrs`, by its
 *  axes, or null. NGFF allows custom axis names and orders; the viewer reads
 *  the spec's t, c, z, y, x, ending in y, x. A store without axes (NGFF 0.3)
 *  is left to the image reader. */
export function axesProblem(attrs: Attrs | null): string | null {
  const multiscales = attrs && Array.isArray(attrs.multiscales) ? attrs.multiscales[0] : null;
  const axes = isRecord(multiscales) && Array.isArray(multiscales.axes) ? multiscales.axes : null;
  if (!axes || axes.length === 0) return null;
  const names = axes.map((a) => String(isRecord(a) ? a.name : a));
  const shown = names.join(', ');
  const odd = names.filter((n) => !VIEWER_AXES.has(n.toLowerCase()));
  if (odd.length) {
    return `This image has axes ${shown}: the viewer reads t, c, z, y and x only (${odd.join(', ')} ${odd.length === 1 ? 'is' : 'are'} not among them). Open it in napari or vizarr.`;
  }
  if (names.slice(-2).join('').toLowerCase() !== 'yx') {
    return `This image has axes ${shown}: the viewer needs y then x last, as NGFF orders them.`;
  }
  return null;
}

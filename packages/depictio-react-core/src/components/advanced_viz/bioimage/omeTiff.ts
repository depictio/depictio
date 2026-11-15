/**
 * OME-XML metadata (as viv's OME-TIFF loader parses it) to the same inputs
 * the OME-Zarr path feeds the viewer: omero-style channel names and colours
 * for `resolveChannels`, and the physical pixel size for the scale bar. Pure
 * (no viv / deck import) so it runs in vitest.
 */

import { abbreviateUnit, type Rgb } from './channels';

/** The part of viv's parsed OME-XML `Image` read here. `Color` arrives as
 *  viv's `[r, g, b, a]`, or as OME's raw signed 32-bit RGBA integer. */
export interface OmeXmlImage {
  Pixels: {
    SizeC: number;
    PhysicalSizeX?: number;
    PhysicalSizeXUnit?: string;
    Channels?: Array<{ Name?: string; Color?: readonly number[] | number }>;
  };
}

/** One channel in the omero `channels` shape `resolveChannels` reads. */
export interface OmeTiffChannel {
  label?: string;
  color?: string;
}

export interface OmeTiffMeta {
  omero: { channels: OmeTiffChannel[] };
  physicalSize: { value: number; unit: string } | null;
}

/** Units that do not measure a length, so a scale bar in them says nothing. */
const NON_LENGTH_UNITS = new Set(['pixel', 'reference frame']);

/** OME's signed 32-bit RGBA integer (e.g. -16776961 is opaque red) to RGB. */
export function omeColorToRgb(color: readonly number[] | number | null | undefined): Rgb | null {
  if (Array.isArray(color)) {
    const [r, g, b] = color;
    return [r, g, b].every((v) => Number.isInteger(v) && v >= 0 && v <= 255)
      ? [r, g, b]
      : null;
  }
  if (typeof color !== 'number' || !Number.isInteger(color)) return null;
  const rgba = color >>> 0;
  return [(rgba >>> 24) & 0xff, (rgba >>> 16) & 0xff, (rgba >>> 8) & 0xff];
}

function rgbToHex(rgb: Rgb): string {
  return `#${rgb.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * Channel names and colours, one entry per `SizeC`, and the level-0 pixel
 * size along x.
 *
 * White is dropped as a colour: it is OME's default (`Color="-1"`), which most
 * writers stamp on every channel, and several channels summed in white read as
 * one grey image. The viewer's fluorescence defaults take over instead.
 */
export function normaliseOmeTiffMetadata(image: OmeXmlImage): OmeTiffMeta {
  const px = image.Pixels;
  const sizeC = Number.isInteger(px.SizeC) && px.SizeC > 0 ? px.SizeC : 1;
  const channels: OmeTiffChannel[] = [];
  for (let i = 0; i < sizeC; i += 1) {
    const ch = px.Channels?.[i];
    const rgb = omeColorToRgb(ch?.Color);
    const white = rgb !== null && rgb.every((v) => v === 255);
    channels.push({
      label: ch?.Name?.trim() || undefined,
      color: rgb && !white ? rgbToHex(rgb) : undefined,
    });
  }
  const value = px.PhysicalSizeX;
  const unit = px.PhysicalSizeXUnit;
  const physicalSize =
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value > 0 &&
    unit &&
    !NON_LENGTH_UNITS.has(unit)
      ? { value, unit: abbreviateUnit(unit) }
      : null;
  return { omero: { channels }, physicalSize };
}

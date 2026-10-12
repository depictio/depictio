/**
 * The collection being edited, before it is saved into the draft: its
 * fields, the workflow it goes to, and which fields the reader has set by
 * hand (a suggestion never overwrites those).
 */
import {
  BUILDER_DC_TYPES,
  SINGLE_FILE_DC_TYPES,
  SPATIALDATA_FORMAT,
  bioimageFormatOf,
  dcTypeAvailability,
  defaultDcProps,
  globToRegex,
  isStorePath,
  regexToGlob,
  seedPropsForCapabilities,
  tagFromPath,
  uniqueTag,
} from 'depictio-react-core';
import type {
  BuilderCapabilities,
  BuilderDcDraft,
  BuilderDcProps,
  BuilderDcType,
  BuilderScanMode,
  BuilderState,
  BuilderSuggestion,
  BuilderWildcard,
  LocatedDc,
} from 'depictio-react-core';

import { baseName } from '../paths';

export interface DcFormTouched {
  tag: boolean;
  type: boolean;
  mode: boolean;
  regex: boolean;
}

export interface DcFormState {
  /** The tag of the collection being edited; null for a new one. */
  originalTag: string | null;
  workflowId: string;
  dc: BuilderDcDraft;
  touched: DcFormTouched;
  /** A genomic tracks manifest was downloaded: the next file picked in the
   *  tree becomes this collection's manifest. */
  awaitingManifest?: boolean;
}

const UNTOUCHED: DcFormTouched = { tag: false, type: false, mode: false, regex: false };
const ALL_TOUCHED: DcFormTouched = { tag: true, type: true, mode: true, regex: true };

/** The type a new collection for `path` starts as: a store is a bioimage
 *  (or a SpatialData table) when the server reads those, anything else a
 *  table until the suggestion says otherwise. */
function initialType(path: string, capabilities: BuilderCapabilities): BuilderDcType {
  if (!isStorePath(path)) return 'table';
  if (dcTypeAvailability('bioimage', capabilities).available) return 'bioimage';
  return 'table';
}

/** A new collection for the file `path`, until the suggestion comes back. */
export function newDcForm(
  state: BuilderState,
  path: string,
  workflowId: string,
  capabilities: BuilderCapabilities,
): DcFormState {
  const type = initialType(path, capabilities);
  return {
    originalTag: null,
    workflowId,
    dc: {
      tag: uniqueTag(state, tagFromPath(path)),
      type,
      mode: 'single',
      path,
      props: defaultDcProps(type, { path }),
    },
    touched: UNTOUCHED,
  };
}

/** A saved collection, loaded back for editing: every field counts as set. */
export function dcFormFromExisting(located: LocatedDc): DcFormState {
  return {
    originalTag: located.dc.tag,
    workflowId: located.workflowId,
    dc: { ...located.dc },
    touched: ALL_TOUCHED,
  };
}

/** Properties for a new type, keeping the format and separator a table and
 *  an image collection share, and the store a SpatialData bioimage and a
 *  SpatialData table share. */
function propsForType(dc: BuilderDcDraft, type: BuilderDcType): BuilderDcProps {
  const p = dc.props;
  if (type === 'table' && p.kind === 'bioimage' && p.format === 'spatialdata') {
    return { kind: 'table', format: SPATIALDATA_FORMAT, spatialdata: { image: p.image_path ?? null } };
  }
  if (type === 'bioimage' && p.kind === 'table' && p.format === SPATIALDATA_FORMAT) {
    return { kind: 'bioimage', format: 'spatialdata', upload: true, image_path: p.spatialdata?.image ?? null };
  }
  const hint =
    (p.kind === 'table' || p.kind === 'image') && type !== 'genomic_tracks' && type !== 'bioimage'
      ? { format: p.format, separator: p.separator ?? null, path: dc.path }
      : { path: dc.path };
  return defaultDcProps(type, hint);
}

export function withType(
  form: DcFormState,
  type: BuilderDcType,
  capabilities: BuilderCapabilities,
): DcFormState {
  if (form.dc.type === type) return form;
  const dc: BuilderDcDraft = {
    ...form.dc,
    type,
    props: seedPropsForCapabilities(propsForType(form.dc, type), capabilities),
  };
  // A GeoJSON or a tree is one file: a scan would be refused.
  if (SINGLE_FILE_DC_TYPES.has(type) && dc.mode === 'recursive') {
    dc.mode = 'single';
    if (!dc.path?.trim()) dc.path = form.dc.path ?? null;
  }
  return { ...form, dc, touched: { ...form.touched, type: true } };
}

/** Switch scan mode. Recursive starts from the suggested pattern, else from
 *  the file's own name. */
export function withMode(
  form: DcFormState,
  mode: BuilderScanMode,
  suggestion: BuilderSuggestion | null,
  activeFile: string | null,
): DcFormState {
  if (form.dc.mode === mode) return form;
  const dc: BuilderDcDraft = { ...form.dc, mode };
  if (mode === 'recursive' && !dc.regex?.trim()) {
    const file = dc.path || activeFile || '';
    const glob = suggestion?.glob || (file ? `**/${baseName(file)}` : '');
    dc.glob = glob;
    dc.regex = suggestion?.regex || globToRegex(glob);
  }
  if (mode === 'single' && !dc.path?.trim()) dc.path = activeFile;
  return { ...form, dc, touched: { ...form.touched, mode: true } };
}

export function withGlob(form: DcFormState, glob: string): DcFormState {
  return {
    ...form,
    dc: { ...form.dc, glob, regex: globToRegex(glob) },
    touched: { ...form.touched, regex: true },
  };
}

export function withRegex(form: DcFormState, regex: string): DcFormState {
  return {
    ...form,
    dc: { ...form.dc, regex, glob: regexToGlob(regex) },
    touched: { ...form.touched, regex: true },
  };
}

/** The suggestion's one-click wildcard: the varying folder becomes a
 *  `{sample}` placeholder of the regex, read into a `sample` column. */
export function withPathWildcard(
  form: DcFormState,
  pathWildcard: { pattern: string; wildcards: BuilderWildcard[] },
): DcFormState {
  return {
    ...form,
    dc: {
      ...form.dc,
      mode: 'recursive',
      regex: pathWildcard.pattern,
      glob: regexToGlob(pathWildcard.pattern),
      wildcards: pathWildcard.wildcards.map((w) => ({ name: w.name, regex: w.regex })),
    },
    touched: { ...form.touched, mode: true, regex: true },
  };
}

/** True when the form already uses the suggestion's path wildcard. */
export function usesPathWildcard(
  form: DcFormState,
  pathWildcard: { pattern: string; wildcards: BuilderWildcard[] } | null | undefined,
): boolean {
  if (!pathWildcard) return false;
  const names = new Set((form.dc.wildcards ?? []).map((w) => w.name.trim()));
  return (
    form.dc.mode === 'recursive' &&
    form.dc.regex === pathWildcard.pattern &&
    pathWildcard.wildcards.every((w) => names.has(w.name))
  );
}

/** The suggestion's pattern, on request. */
export function withSuggestedPattern(form: DcFormState, s: BuilderSuggestion): DcFormState {
  return {
    ...form,
    dc: {
      ...form.dc,
      mode: s.mode,
      glob: s.glob ?? (s.regex ? regexToGlob(s.regex) : null),
      regex: s.regex,
    },
  };
}

/** The type a suggestion stands for: a MultiQC parquet is a MultiQC
 *  collection whatever the server's generic guess; a type this page does not
 *  know reads as a table. */
export function suggestedType(s: BuilderSuggestion): BuilderDcType {
  if (s.multiqc) return 'multiqc';
  return BUILDER_DC_TYPES.includes(s.type) ? s.type : 'table';
}

/** Properties for a suggested type, with what the suggestion read of the
 *  file: a store's format, NGFF version and first image, a track's format. */
function suggestedProps(type: BuilderDcType, s: BuilderSuggestion, path: string | null | undefined): BuilderDcProps {
  const props = defaultDcProps(type, { format: s.format, separator: s.separator, path });
  if (props.kind === 'bioimage') {
    const format = bioimageFormatOf(path, s.store?.format ?? s.format);
    return {
      ...props,
      format,
      ngff_version: s.store?.ngff_version ?? null,
      image_path: format === 'spatialdata' ? s.store?.images[0] ?? null : null,
    };
  }
  if (props.kind === 'genomic_tracks' && s.tracks?.format) {
    return { ...props, default_format: s.tracks.format };
  }
  if (props.kind === 'table' && props.format === SPATIALDATA_FORMAT) {
    return {
      ...props,
      spatialdata: { table: s.store?.tables[0], image: s.store?.images[0] ?? null },
    };
  }
  return props;
}

/** Fill what the reader has not set by hand from the server's suggestion. A
 *  type the server does not build is not taken (the server should not
 *  suggest one). */
export function applySuggestion(
  state: BuilderState,
  form: DcFormState,
  s: BuilderSuggestion,
  capabilities: BuilderCapabilities,
): DcFormState {
  const dc: BuilderDcDraft = { ...form.dc };
  if (!form.touched.tag && s.tag) dc.tag = uniqueTag(state, s.tag, form.originalTag);
  const type = suggestedType(s);
  if (!form.touched.type && dcTypeAvailability(type, capabilities).available) {
    dc.type = type;
    dc.props = seedPropsForCapabilities(suggestedProps(type, s, dc.path), capabilities);
  }
  if (!form.touched.mode) dc.mode = s.mode;
  if (!form.touched.regex) {
    dc.regex = s.regex;
    dc.glob = s.glob ?? (s.regex ? regexToGlob(s.regex) : null);
  }
  return { ...form, dc };
}

/** Use `path` (relative to the data root) as a genomic tracks collection's
 *  manifest: one file, its uris relative to the data root. The tag, type and
 *  mode count as set, so the manifest's own suggestion changes none. */
export function withManifest(form: DcFormState, path: string): DcFormState {
  const props = form.dc.props.kind === 'genomic_tracks' ? { ...form.dc.props, tracks_base_path: '' } : form.dc.props;
  return {
    ...form,
    dc: { ...form.dc, mode: 'single', path, props },
    touched: { ...form.touched, tag: true, type: true, mode: true },
    awaitingManifest: false,
  };
}

/** True when the collection's matches are stores (`*.zarr` folders), not
 *  files: zarr bioimages and SpatialData tables. */
export function matchesStores(dc: BuilderDcDraft): boolean {
  if (dc.props.kind === 'bioimage') return dc.props.format !== 'ome-tiff';
  return dc.props.kind === 'table' && dc.props.format === SPATIALDATA_FORMAT;
}

/** A suggestion whose pattern differs from the form's, worth offering. */
export function suggestionDiffers(form: DcFormState, s: BuilderSuggestion | null): boolean {
  if (!s || !s.regex) return false;
  return form.dc.mode !== s.mode || (form.dc.regex ?? '') !== s.regex;
}

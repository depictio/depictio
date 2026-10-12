/**
 * The collection being edited, before it is saved into the draft: its
 * fields, the workflow it goes to, and which fields the reader has set by
 * hand (a suggestion never overwrites those).
 */
import {
  SINGLE_FILE_DC_TYPES,
  defaultDcProps,
  globToRegex,
  regexToGlob,
  tagFromPath,
  uniqueTag,
} from 'depictio-react-core';
import type {
  BuilderDcDraft,
  BuilderDcProps,
  BuilderDcType,
  BuilderScanMode,
  BuilderState,
  BuilderSuggestion,
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
}

const UNTOUCHED: DcFormTouched = { tag: false, type: false, mode: false, regex: false };
const ALL_TOUCHED: DcFormTouched = { tag: true, type: true, mode: true, regex: true };

/** A new collection for the file `path`, until the suggestion comes back. */
export function newDcForm(state: BuilderState, path: string, workflowId: string): DcFormState {
  return {
    originalTag: null,
    workflowId,
    dc: {
      tag: uniqueTag(state, tagFromPath(path)),
      type: 'table',
      mode: 'single',
      path,
      props: defaultDcProps('table', { path }),
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
 *  an image collection share. */
function propsForType(dc: BuilderDcDraft, type: BuilderDcType): BuilderDcProps {
  const p = dc.props;
  const hint =
    p.kind === 'table' || p.kind === 'image'
      ? { format: p.format, separator: p.separator ?? null, path: dc.path }
      : { path: dc.path };
  return defaultDcProps(type, hint);
}

export function withType(form: DcFormState, type: BuilderDcType): DcFormState {
  if (form.dc.type === type) return form;
  const dc: BuilderDcDraft = { ...form.dc, type, props: propsForType(form.dc, type) };
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
 *  collection whatever the server's generic guess. */
export function suggestedType(s: BuilderSuggestion): BuilderDcType {
  return s.multiqc ? 'multiqc' : s.type;
}

/** Fill what the reader has not set by hand from the server's suggestion. */
export function applySuggestion(
  state: BuilderState,
  form: DcFormState,
  s: BuilderSuggestion,
): DcFormState {
  const dc: BuilderDcDraft = { ...form.dc };
  if (!form.touched.tag && s.tag) dc.tag = uniqueTag(state, s.tag, form.originalTag);
  if (!form.touched.type) {
    const type = suggestedType(s);
    dc.type = type;
    dc.props = defaultDcProps(type, { format: s.format, separator: s.separator, path: dc.path });
  }
  if (!form.touched.mode) dc.mode = s.mode;
  if (!form.touched.regex) {
    dc.regex = s.regex;
    dc.glob = s.glob ?? (s.regex ? regexToGlob(s.regex) : null);
  }
  return { ...form, dc };
}

/** A suggestion whose pattern differs from the form's, worth offering. */
export function suggestionDiffers(form: DcFormState, s: BuilderSuggestion | null): boolean {
  if (!s || !s.regex) return false;
  return form.dc.mode !== s.mode || (form.dc.regex ?? '') !== s.regex;
}

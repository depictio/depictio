/**
 * What the builder does with a folder Depictio recognises: read the folder the
 * way the run-folder dialog does, tell the reader which pipeline and template
 * it found, and offer to start the draft from that template.
 *
 * Nothing replaces the reader's work unasked:
 * - a hand-off from the dialog with `intent: edit-template` loads the template
 *   as the draft, but only into an empty draft (a saved one is kept, and the
 *   card offers the template instead);
 * - an empty draft takes the recognised engine (nextflow...) in place of the
 *   builder's default, once per folder;
 * - loading the template over a draft with collections is the reader's click.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch } from 'react';

import {
  DEFAULT_ENGINE,
  inspectFolder,
  stateFromTemplateDraft,
} from 'depictio-react-core';
import type {
  BuilderAction,
  BuilderHandoff,
  BuilderRootSpec,
  BuilderState,
  BuilderTemplateDraft,
  FolderInspection,
} from 'depictio-react-core';

import { fetchTemplateDraft } from '../../fromRun/useTemplateDraft';

export type RootDetection =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; result: FolderInspection }
  | { status: 'error' };

/** The folder read like the run-folder dialog reads it: which pipeline made
 *  it, which template fits. A failed read is not an error to show: the
 *  builder works without it. */
export function useRootDetection(root: BuilderRootSpec | null): RootDetection {
  const [detection, setDetection] = useState<RootDetection>({ status: 'idle' });
  const location = root?.data_root ?? null;
  const storageKey = JSON.stringify(root?.storage ?? null);

  useEffect(() => {
    if (!location) {
      setDetection({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setDetection({ status: 'loading' });
    inspectFolder(location, { signal: controller.signal, storage: root?.storage ?? null })
      .then((result) => {
        if (!controller.signal.aborted) setDetection({ status: 'ready', result });
      })
      .catch(() => {
        if (!controller.signal.aborted) setDetection({ status: 'error' });
      });
    return () => controller.abort();
    // `root.storage` is a fresh object per render; its key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location, storageKey]);

  return detection;
}

/** A draft with nothing in it: no collection, no link. */
export function isDraftEmpty(state: BuilderState): boolean {
  return state.links.length === 0 && state.workflows.every((w) => w.data_collections.length === 0);
}

/** Still the builder's own starting workflow, untouched. */
function isPristine(state: BuilderState): boolean {
  return (
    isDraftEmpty(state) &&
    state.workflows.length === 1 &&
    state.workflows[0].engine === DEFAULT_ENGINE &&
    !state.workflows[0].engine_version
  );
}

export type TemplateStartState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; result: BuilderTemplateDraft }
  | { status: 'error'; error: string };

export interface TemplateStart {
  detection: RootDetection;
  /** The template that fits the folder, when one does. */
  templateId: string | null;
  /** The recognised workflow engine, when the folder tells. */
  engine: string | null;
  state: TemplateStartState;
  /** The dialog asked for the template, but the folder already has a saved
   *  draft, which was kept. */
  keptSavedDraft: boolean;
  /** Replace the draft with the template's. */
  load: () => void;
  /** Forget the template the draft came from (the draft itself is kept). */
  dismiss: () => void;
}

export function useTemplateStart(options: {
  handoff: BuilderHandoff | null;
  root: BuilderRootSpec | null;
  /** The folder whose saved draft the page has loaded (see `useBuilderDraft`). */
  loadedRoot: string | null;
  draft: BuilderState;
  dispatch: Dispatch<BuilderAction>;
}): TemplateStart {
  const { handoff, root, loadedRoot, draft, dispatch } = options;
  const detection = useRootDetection(root);
  const [state, setState] = useState<TemplateStartState>({ status: 'idle' });
  const [keptSavedDraft, setKeptSavedDraft] = useState(false);
  const handedOver = useRef(false);
  const engineSetFor = useRef<string | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const location = root?.data_root ?? null;
  const locationRef = useRef(location);
  locationRef.current = location;

  // A template loaded for one folder says nothing about the next: a new
  // folder starts over with its own detection and its own choices.
  useEffect(() => {
    setState({ status: 'idle' });
    setKeptSavedDraft(false);
  }, [location]);

  const detected = detection.status === 'ready' ? detection.result.detected : null;
  const templateId = detected?.template_id ?? handoff?.detected?.templateId ?? null;
  const engine = detected?.engine ?? handoff?.detected?.engine ?? null;
  const ready = Boolean(root) && loadedRoot === root?.data_root;

  const load = useCallback(
    (id?: string) => {
      const target = id ?? templateId;
      if (!target) return;
      const requestedFor = locationRef.current;
      setState({ status: 'loading' });
      fetchTemplateDraft(target)
        .then((result) => {
          // The reader moved to another folder meanwhile: not its draft.
          if (locationRef.current !== requestedFor) return;
          const next = stateFromTemplateDraft(result);
          if (!next || !result.editable) {
            setState({
              status: 'error',
              error: result.reason || 'The builder cannot express anything of this template.',
            });
            return;
          }
          dispatch({ type: 'state/replace', state: next });
          setKeptSavedDraft(false);
          setState({ status: 'loaded', result });
        })
        .catch((err: Error) => {
          if (locationRef.current !== requestedFor) return;
          setState({ status: 'error', error: err.message || 'The template could not be read.' });
        });
    },
    [templateId, dispatch],
  );

  // The dialog's "start from the template", applied once the folder's saved
  // draft is known: only into an empty draft.
  useEffect(() => {
    if (!ready || handedOver.current) return;
    if (handoff?.intent !== 'edit-template' || !handoff.templateId) return;
    handedOver.current = true;
    if (isDraftEmpty(draftRef.current)) load(handoff.templateId);
    else setKeptSavedDraft(true);
  }, [ready, handoff, load]);

  // The recognised engine, instead of the default, for a draft nobody has
  // touched. A template loaded as the draft brings its own.
  useEffect(() => {
    if (!ready || !root || !engine) return;
    if (engineSetFor.current === root.data_root) return;
    if (handoff?.intent === 'edit-template' && !handedOver.current) return;
    engineSetFor.current = root.data_root;
    const current = draftRef.current;
    if (!isPristine(current)) return;
    dispatch({
      type: 'workflow/patch',
      id: current.workflows[0].id,
      patch: { engine: engine.trim().toLowerCase() },
    });
  }, [ready, root, engine, handoff, dispatch, state.status]);

  const dismiss = useCallback(() => {
    setState({ status: 'idle' });
    setKeptSavedDraft(false);
  }, []);

  return { detection, templateId, engine, state, keptSavedDraft, load: () => load(), dismiss };
}

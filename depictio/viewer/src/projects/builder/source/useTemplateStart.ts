/**
 * What the builder does with a folder Depictio recognises: read the folder the
 * way the run-folder dialog does, tell the reader which pipeline and template
 * it found, and offer to start the draft from that template.
 *
 * The template is opened whole: its collections are shown read-only and the
 * reader's changes are kept as edits of it (`BuilderState.base`), never as a
 * conversion that would drop its recipes and dashboards.
 *
 * Nothing of the reader's work is lost unasked:
 * - a hand-off from the dialog opens what was chosen there: with
 *   `intent: edit-template`, that template with the dialog's removals and
 *   variables; with `scratch`, a draft of the reader's own. A saved draft of
 *   the folder is replaced, and kept in memory to restore;
 * - an empty draft takes the recognised engine (nextflow...) in place of the
 *   builder's default, once per folder;
 * - loading the template over a draft with collections is the reader's click.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch } from 'react';

import {
  DEFAULT_ENGINE,
  initialBuilderState,
  inspectFolder,
  stateFromTemplateBase,
} from 'depictio-react-core';
import type {
  BuilderAction,
  BuilderHandoff,
  BuilderRootSpec,
  BuilderProjectFields,
  BuilderState,
  BuilderTemplateDescription,
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
  return (
    !state.base &&
    state.links.length === 0 &&
    state.workflows.every((w) => w.data_collections.length === 0)
  );
}

/** What the reader already said of the project, so a template opened as
 *  the draft does not take it back. */
function projectSaid(state: BuilderState): Partial<BuilderProjectFields> {
  const said: Partial<BuilderProjectFields> = {};
  if (state.project.name.trim()) said.name = state.project.name;
  if (state.project.description.trim()) said.description = state.project.description;
  if (state.project.is_public) said.is_public = true;
  return said;
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
  | { status: 'loaded'; result: BuilderTemplateDescription }
  | { status: 'error'; error: string };

export interface TemplateStart {
  detection: RootDetection;
  /** The template that fits the folder, when one does. */
  templateId: string | null;
  /** The recognised workflow engine, when the folder tells. */
  engine: string | null;
  state: TemplateStartState;
  /** The draft the template replaced (another saved draft of this folder),
   *  kept to restore; null when nothing was replaced. */
  replaced: BuilderState | null;
  /** Put the replaced draft back. */
  restore: () => void;
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
  const [replaced, setReplaced] = useState<BuilderState | null>(null);
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
    setReplaced(null);
  }, [location]);

  const detected = detection.status === 'ready' ? detection.result.detected : null;
  const templateId = detected?.template_id ?? handoff?.detected?.templateId ?? null;
  const engine = detected?.engine ?? handoff?.detected?.engine ?? null;
  const ready = Boolean(root) && loadedRoot === root?.data_root;

  const load = useCallback(
    (id?: string, given: { remove?: string[]; variables?: Record<string, string> } | null = null) => {
      const target = id ?? templateId;
      if (!target) return;
      const requestedFor = locationRef.current;
      setState({ status: 'loading' });
      fetchTemplateDraft(target)
        .then((result) => {
          // The reader moved to another folder meanwhile: not its draft.
          if (locationRef.current !== requestedFor) return;
          const current = draftRef.current;
          dispatch({ type: 'state/replace', state: stateFromTemplateBase(result, projectSaid(current)) });
          // What the dialog chose: its removals ("Only the found", the same
          // `scopeRemovals` its Create sends) and its variables.
          for (const tag of given?.remove ?? []) dispatch({ type: 'base/remove', tag });
          for (const [name, value] of Object.entries(given?.variables ?? {})) {
            dispatch({ type: 'base/variable', name, value });
          }
          setReplaced(isDraftEmpty(current) ? null : current);
          setState({ status: 'loaded', result });
        })
        .catch((err: Error) => {
          if (locationRef.current !== requestedFor) return;
          setState({ status: 'error', error: err.message || 'The template could not be read.' });
        });
    },
    [templateId, dispatch],
  );

  // What the dialog chose is what opens, once the folder's saved draft is
  // known. A saved draft never takes its place silently: it is replaced and
  // kept to restore (`replaced`), whatever template it edits.
  useEffect(() => {
    if (!ready || handedOver.current) return;
    if (handoff?.intent === 'edit-template' && handoff.templateId) {
      handedOver.current = true;
      load(handoff.templateId, { remove: handoff.remove, variables: handoff.variables });
      return;
    }
    if (handoff?.intent === 'scratch') {
      handedOver.current = true;
      // "Custom workflows": the reader's own collections, not a template's.
      const current = draftRef.current;
      if (!current.base) return;
      dispatch({ type: 'state/replace', state: { ...initialBuilderState(), project: current.project } });
      setReplaced(current);
    }
  }, [ready, handoff, load, dispatch]);

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
    // Starting over leaves a pristine draft: the engine is read again for it.
    engineSetFor.current = null;
    setState({ status: 'idle' });
    setReplaced(null);
  }, []);

  const restore = useCallback(() => {
    if (!replaced) return;
    dispatch({ type: 'state/replace', state: replaced });
    setReplaced(null);
    setState({ status: 'idle' });
  }, [replaced, dispatch]);

  return { detection, templateId, engine, state, replaced, restore, load: () => load(), dismiss };
}

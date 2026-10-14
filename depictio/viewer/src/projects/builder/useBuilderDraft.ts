/**
 * The draft of the current data root: loaded from localStorage when the root
 * is set (`depictio:project-builder:draft:v1:<data_root>`), saved after every
 * edit, so a refresh never loses the work. Another root has its own draft;
 * one without a saved draft starts fresh but keeps the project fields
 * already typed.
 *
 * The root and its draft change together, in one reducer state, so a draft
 * is never saved under another root's key.
 */
import { useCallback, useEffect, useReducer, useRef } from 'react';
import type { Dispatch } from 'react';

import {
  builderReducer,
  clearBuilderDraft,
  initialBuilderState,
  loadBuilderDraft,
  saveBuilderDraft,
} from 'depictio-react-core';
import type { BuilderAction, BuilderState } from 'depictio-react-core';

interface Holder {
  root: string | null;
  draft: BuilderState;
}

/** `draft` null: none was saved; start fresh with the project fields typed
 *  so far, read here rather than at dispatch so an edit still queued is
 *  never lost. */
type HolderAction = BuilderAction | { type: 'root/load'; root: string; draft: BuilderState | null };

function holderReducer(holder: Holder, action: HolderAction): Holder {
  if (action.type === 'root/load') {
    return {
      root: action.root,
      draft: action.draft ?? { ...initialBuilderState(), project: holder.draft.project },
    };
  }
  const draft = builderReducer(holder.draft, action);
  return draft === holder.draft ? holder : { ...holder, draft };
}

export function useBuilderDraft(dataRoot: string | null): {
  state: BuilderState;
  dispatch: Dispatch<BuilderAction>;
  /** The folder whose saved draft (or fresh one) the state holds: null until
   *  the first folder is read. */
  loadedRoot: string | null;
  /** Drop the draft of this root and start over. */
  reset: () => void;
  /** Forget the saved draft (the project was created). */
  forget: () => void;
} {
  const [holder, dispatchHolder] = useReducer(holderReducer, undefined, () => ({
    root: null,
    draft: initialBuilderState(),
  }));
  const holderRef = useRef(holder);
  holderRef.current = holder;

  useEffect(() => {
    if (!dataRoot || dataRoot === holderRef.current.root) return;
    dispatchHolder({ type: 'root/load', root: dataRoot, draft: loadBuilderDraft(dataRoot) });
  }, [dataRoot]);

  useEffect(() => {
    if (holder.root) saveBuilderDraft(holder.root, holder.draft);
  }, [holder]);

  const dispatch = useCallback((action: BuilderAction) => dispatchHolder(action), []);

  const reset = useCallback(() => {
    const root = holderRef.current.root;
    if (root) clearBuilderDraft(root);
    dispatchHolder({ type: 'state/replace', state: initialBuilderState() });
  }, []);

  const forget = useCallback(() => {
    const root = holderRef.current.root;
    if (root) clearBuilderDraft(root);
  }, []);

  return { state: holder.draft, dispatch, loadedRoot: holder.root, reset, forget };
}

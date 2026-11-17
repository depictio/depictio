import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchDashboardAnnotations,
  mergeAccountAndLocal,
  readBrowserAnnotations,
  saveDashboardAnnotations,
  splitForAccount,
  writeBrowserAnnotations,
} from 'depictio-react-core';
import type { DashboardAnnotations } from 'depictio-react-core';

/** Where a reader's annotations are kept: the account for a signed-in
 *  account (and single-user mode), the browser for a temporary or anonymous one. */
export type AnnotationStorage = 'account' | 'browser';

export interface DashboardAnnotationsState {
  annotations: DashboardAnnotations | null;
  setAnnotations: (next: DashboardAnnotations | null) => void;
  /** False until the first read answered. Groups are derived only after it. */
  loaded: boolean;
  storage: AnnotationStorage | null;
  /** The browser keeps nothing: annotations last for this page only. */
  browserUnavailable: boolean;
  /** The account read was refused (lost access): nothing is shown. */
  loadError: string | null;
  /** The last account save failed; the panel keeps its state. */
  saveError: string | null;
  /** Unsaved changes waiting for the debounce. */
  pending: boolean;
}

const SAVE_DELAY_MS = 800;

/**
 * The reader's annotations on a dashboard family, read once and written back
 * after a pause. A failed account save is kept on screen and retried with the
 * next change; it is never dropped silently.
 */
export function useDashboardAnnotations(
  scopeId: string | undefined,
  storage: AnnotationStorage | null,
): DashboardAnnotationsState {
  const [annotations, setState] = useState<DashboardAnnotations | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [browserUnavailable, setBrowserUnavailable] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<DashboardAnnotations | null>(null);
  // The account half the server holds, as sent: a change that only touches
  // the browser half (an annotation from a dropped file) sends nothing.
  const sentKey = useRef('null');

  useEffect(() => {
    setLoaded(false);
    setLoadError(null);
    setSaveError(null);
    setState(null);
    latest.current = null;
    if (!scopeId || !storage) return;
    if (storage === 'browser') {
      const read = readBrowserAnnotations(scopeId);
      setBrowserUnavailable(!read.ok);
      const value = read.ok ? read.value : null;
      latest.current = value;
      setState(value);
      setLoaded(true);
      return;
    }
    let cancelled = false;
    void fetchDashboardAnnotations(scopeId).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        // Annotations read from a dropped file live in this browser only.
        const read = readBrowserAnnotations(scopeId);
        setBrowserUnavailable(!read.ok);
        const merged = mergeAccountAndLocal(res.annotations, read.ok ? read.value : null);
        sentKey.current = JSON.stringify(splitForAccount(merged).account);
        latest.current = merged;
        setState(merged);
      } else {
        setLoadError(
          res.status === 403
            ? res.detail || "You can no longer read this dashboard's annotations."
            : 'Your annotations could not be loaded.',
        );
      }
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [scopeId, storage]);

  const flush = useCallback(async () => {
    if (!scopeId) return;
    const value = latest.current;
    const account = splitForAccount(value).account;
    const key = JSON.stringify(account);
    if (key === sentKey.current) {
      setPending(false);
      return;
    }
    const res = await saveDashboardAnnotations(scopeId, account);
    if (res.ok) sentKey.current = key;
    // A newer change may have landed while this one was in flight; its own
    // timer saves it.
    if (latest.current !== value) return;
    setPending(false);
    setSaveError(
      res.ok
        ? null
        : res.detail
          ? `Not saved to your account: ${res.detail}`
          : 'Not saved to your account. Your annotations stay here; the next change retries.',
    );
  }, [scopeId]);

  // Leaving the page inside the debounce: send what is pending now.
  useEffect(() => {
    if (!scopeId || storage !== 'account') return;
    const onHide = () => {
      if (!timer.current) return;
      clearTimeout(timer.current);
      timer.current = null;
      const account = splitForAccount(latest.current).account;
      if (JSON.stringify(account) === sentKey.current) return;
      void saveDashboardAnnotations(scopeId, account, { keepalive: true });
    };
    window.addEventListener('pagehide', onHide);
    return () => {
      window.removeEventListener('pagehide', onHide);
      onHide();
    };
  }, [scopeId, storage]);

  const setAnnotations = useCallback(
    (next: DashboardAnnotations | null) => {
      latest.current = next;
      setState(next);
      if (!scopeId || !storage) return;
      if (storage === 'browser') {
        setBrowserUnavailable(!writeBrowserAnnotations(scopeId, next));
        return;
      }
      // The browser half is written now; only the account half is sent.
      setBrowserUnavailable(!writeBrowserAnnotations(scopeId, splitForAccount(next).local));
      setPending(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        timer.current = null;
        void flush();
      }, SAVE_DELAY_MS);
    },
    [scopeId, storage, flush],
  );

  return {
    annotations,
    setAnnotations,
    loaded,
    storage,
    browserUnavailable,
    loadError,
    saveError,
    pending,
  };
}

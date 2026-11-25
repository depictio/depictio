import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import { MSG, THUMB_HEIGHT, THUMB_WIDTH, parseFrameMessage, tileKey } from './previewProtocol';
import type { PreviewPatch, PreviewScheme, PreviewStyles } from './previewProtocol';

/** An edit reaches the frame this long after the last one. */
const APPLY_DEBOUNCE_MS = 60;
/** A loaded frame that has not said "ready" by now cannot take live edits. */
const READY_GRACE_MS = 4000;

export interface FrameBridge {
  iframeRef: RefObject<HTMLIFrameElement>;
  /** The frame said "ready": edits are applied live. */
  frameReady: boolean;
  /** The frame loaded but never said "ready". */
  unresponsive: boolean;
  /** Thumbnails by `tab_id:component_id`, as data URLs. */
  thumbs: Record<string, string>;
  /** Snapshots (inert HTML) of the tiles that are not Plotly figures, by the same key. */
  snapshots: Record<string, string>;
  /** The report's look, to render a snapshot with. */
  styles: PreviewStyles | null;
  onFrameLoad: () => void;
  /** Scrolls the frame to a tile (scroll sync); the frame does not report it back. */
  scrollFrameTo: (tabId: string, componentId: string) => void;
}

/**
 * The page's side of the preview protocol.
 *
 * Messages are accepted from the frame's own window only. On "ready" the
 * current patch and the app's colour scheme go over and the frame is asked
 * for thumbnails (after the scheme, so the styles it reports are the ones
 * shown); afterwards every new patch is posted after a short debounce, and
 * the scheme again whenever the app's changes. The frame has an opaque
 * origin, so no target origin can name it.
 */
export function useFrameBridge(
  frameUrl: string | null,
  patch: PreviewPatch | null,
  onSelect: (tabId: string, componentId: string) => void,
  scheme: PreviewScheme,
  /** The tile at the top of the frame's viewport changed (the reader scrolled it). */
  onVisible?: (tabId: string, componentId: string) => void,
): FrameBridge {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [frameReady, setFrameReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [unresponsive, setUnresponsive] = useState(false);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const [styles, setStyles] = useState<PreviewStyles | null>(null);
  const patchRef = useRef(patch);
  patchRef.current = patch;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onVisibleRef = useRef(onVisible);
  onVisibleRef.current = onVisible;
  const schemeRef = useRef(scheme);
  schemeRef.current = scheme;
  // The scheme the frame was last told, so "ready" and the effect below do
  // not both send it.
  const sentSchemeRef = useRef<PreviewScheme | null>(null);

  const post = useCallback((message: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(message, '*');
  }, []);

  // Loads of the current document. A second one means the frame left the
  // preview (a link followed inside it): that page is not the report, so it
  // is told nothing and heard no more, until the next preview is loaded.
  const loadsRef = useRef(0);

  // A new document: wait for its "ready" again.
  useEffect(() => {
    loadsRef.current = 0;
    setFrameReady(false);
    setLoaded(false);
    setUnresponsive(false);
  }, [frameUrl]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frame = iframeRef.current?.contentWindow;
      if (!frame || event.source !== frame || loadsRef.current > 1) return;
      const message = parseFrameMessage(event.data);
      if (!message) return;
      if (message.type === MSG.ready) {
        setFrameReady(true);
        setUnresponsive(false);
        if (patchRef.current) post({ type: MSG.apply, patch: patchRef.current });
        sentSchemeRef.current = schemeRef.current;
        post({ type: MSG.scheme, scheme: schemeRef.current });
        post({ type: MSG.thumbnails, width: THUMB_WIDTH, height: THUMB_HEIGHT });
      } else if (message.type === MSG.select) {
        onSelectRef.current(message.tab_id, message.component_id);
      } else if (message.type === MSG.visible) {
        onVisibleRef.current?.(message.tab_id, message.component_id);
      } else if (message.type === MSG.thumbnail) {
        const key = tileKey(message.tab_id, message.component_id);
        setThumbs((prev) => ({ ...prev, [key]: message.data_url }));
      } else if (message.type === MSG.snapshot) {
        const key = tileKey(message.tab_id, message.component_id);
        setSnapshots((prev) => ({ ...prev, [key]: message.html }));
      } else if (message.type === MSG.styles) {
        setStyles(message.styles);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [post]);

  useEffect(() => {
    if (!frameReady || !patch) return;
    const timer = window.setTimeout(() => post({ type: MSG.apply, patch }), APPLY_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [frameReady, patch, post]);

  // The app's scheme changed while the frame is up: the frame follows.
  useEffect(() => {
    if (!frameReady || sentSchemeRef.current === scheme) return;
    sentSchemeRef.current = scheme;
    post({ type: MSG.scheme, scheme });
  }, [frameReady, scheme, post]);

  useEffect(() => {
    if (!loaded || frameReady) return;
    const timer = window.setTimeout(() => setUnresponsive(true), READY_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [loaded, frameReady]);

  const onFrameLoad = useCallback(() => {
    loadsRef.current += 1;
    if (loadsRef.current > 1) setFrameReady(false);
    setLoaded(true);
  }, []);
  const scrollFrameTo = useCallback(
    (tabId: string, componentId: string) =>
      post({ type: MSG.scrollTo, tab_id: tabId, component_id: componentId }),
    [post],
  );

  return { iframeRef, frameReady, unresponsive, thumbs, snapshots, styles, onFrameLoad, scrollFrameTo };
}

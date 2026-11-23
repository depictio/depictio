import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import { MSG, THUMB_HEIGHT, THUMB_WIDTH, parseFrameMessage, tileKey } from './previewProtocol';
import type { PreviewPatch, PreviewStyles } from './previewProtocol';

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
}

/**
 * The page's side of the preview protocol.
 *
 * Messages are accepted from the frame's own window only. On "ready" the
 * current patch goes over and the frame is asked for thumbnails; afterwards
 * every new patch is posted after a short debounce. The frame has an opaque
 * origin, so no target origin can name it.
 */
export function useFrameBridge(
  frameUrl: string | null,
  patch: PreviewPatch | null,
  onSelect: (tabId: string, componentId: string) => void,
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

  const post = useCallback((message: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(message, '*');
  }, []);

  // A new document: wait for its "ready" again.
  useEffect(() => {
    setFrameReady(false);
    setLoaded(false);
    setUnresponsive(false);
  }, [frameUrl]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frame = iframeRef.current?.contentWindow;
      if (!frame || event.source !== frame) return;
      const message = parseFrameMessage(event.data);
      if (!message) return;
      if (message.type === MSG.ready) {
        setFrameReady(true);
        setUnresponsive(false);
        if (patchRef.current) post({ type: MSG.apply, patch: patchRef.current });
        post({ type: MSG.thumbnails, width: THUMB_WIDTH, height: THUMB_HEIGHT });
      } else if (message.type === MSG.select) {
        onSelectRef.current(message.tab_id, message.component_id);
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

  useEffect(() => {
    if (!loaded || frameReady) return;
    const timer = window.setTimeout(() => setUnresponsive(true), READY_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [loaded, frameReady]);

  const onFrameLoad = useCallback(() => setLoaded(true), []);

  return { iframeRef, frameReady, unresponsive, thumbs, snapshots, styles, onFrameLoad };
}

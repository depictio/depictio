/**
 * Catalog-preview app shell: switches between the Gallery (all outputs on one
 * page) and a single output's detail view. The CLI decides the landing view via
 * `initialOutputId` — `catalog gallery` leaves it null (grid first), `catalog
 * preview <id>` sets it (straight into detail). Both embed the same payload
 * schema, so this is the only place that branches.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AdvancedVizConfigDraftProvider } from 'depictio-react-core';
import Gallery from './Gallery';
import OutputView from './OutputView';
import type { CatalogGlobal, OutputEntry } from './shared';

/** Read render_id from the URL hash (#render_id=...) — works inside an iframe
 *  without any backend-side injection, so no backend restart required. */
function readHashRenderId(): string | null {
  const m = window.location.hash.match(/[#&]render_id=([^&]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Read the tile height the embedder wants the single render pinned to
 *  (#tile_h=204). Set by the builder's catalog picker for card renders, whose
 *  viewport is deliberately taller than the tile so the metric strip's tooltip
 *  has somewhere to go — an iframe clips it otherwise. Absent everywhere else,
 *  and the render then fills the viewport as before. */
function readHashTileHeight(): number | null {
  const m = window.location.hash.match(/[#&]tile_h=(\d+)/);
  if (!m) return null;
  const value = Number(m[1]);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Read the selected output id from the URL hash (#output=...). */
function readHashOutputId(): string | null {
  const m = window.location.hash.match(/[#&]output=([^&]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Forward a Tier-2 control change to whoever embedded this preview.
 *
 * The preview runs in its own document inside an iframe, so the builder's
 * in-process draft context cannot reach across. Without this hop, a dot size or
 * palette tuned in the picker's own settings popover showed in the preview and
 * was then silently dropped by Add, which is precisely where the preview is
 * supposed to be telling the truth about what you are about to get.
 *
 * The message carries the render it belongs to so the embedder can ignore
 * anything that arrives after the selection has moved on, and it is posted to
 * this document's own origin, which is the embedder's too. */
function postConfigDraft(renderId: string | null) {
  return (componentIndex: string, patch: Record<string, unknown>) => {
    if (window.parent === window) return;
    window.parent.postMessage(
      { type: 'depictio:viz-config-draft', renderId, componentIndex, patch },
      window.location.origin,
    );
  };
}

const CatalogApp: React.FC<{ g: CatalogGlobal }> = ({ g }) => {
  const tools = g.tools || [];
  const totalOutputs = useMemo(() => tools.reduce((n, t) => n + t.outputs.length, 0), [tools]);
  const [selected, setSelected] = useState<string | null>(
    readHashOutputId() ?? g.initialOutputId ?? null,
  );

  // Hash takes priority over injected value (works without backend restart).
  const renderId = readHashRenderId() ?? g.initialRenderId ?? null;
  const tileHeight = readHashTileHeight();

  // The embedder paints the surface behind a pinned tile, so the document must
  // not paint one of its own: an opaque page would draw a slab across the
  // headroom the tile's tooltips need. `html` is the one that matters —
  // Mantine's reset leaves `body` transparent and colours the root element.
  useEffect(() => {
    if (tileHeight === null) return;
    const root = document.documentElement;
    const previous = { html: root.style.background, body: document.body.style.background };
    root.style.background = 'transparent';
    document.body.style.background = 'transparent';
    return () => {
      root.style.background = previous.html;
      document.body.style.background = previous.body;
    };
  }, [tileHeight]);

  // Drive gallery↔detail through the History API so the browser back/forward
  // buttons navigate (and #output=<id> deep-links a detail view).
  const navigate = useCallback((id: string | null) => {
    setSelected(id);
    window.history.pushState(
      { outputId: id },
      '',
      id ? `#output=${encodeURIComponent(id)}` : window.location.pathname,
    );
  }, []);

  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      const id = (e.state?.outputId as string | null | undefined) ?? readHashOutputId();
      setSelected(id ?? null);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const draftSink = useMemo(() => postConfigDraft(renderId), [renderId]);

  const entry: OutputEntry | undefined = useMemo(() => {
    if (!selected) return undefined;
    for (const t of tools) {
      const found = t.outputs.find((o) => o.output.id === selected);
      if (found) return found;
    }
    return undefined;
  }, [selected, tools]);

  const body = entry ? (
    <OutputView
      entry={entry}
      onBack={totalOutputs > 1 ? () => navigate(null) : undefined}
      theme={g.theme}
      renderId={renderId}
      tileHeight={tileHeight}
    />
  ) : (
    <Gallery tools={tools} onOpen={navigate} theme={g.theme} />
  );

  return (
    <AdvancedVizConfigDraftProvider value={draftSink}>{body}</AdvancedVizConfigDraftProvider>
  );
};

export default CatalogApp;

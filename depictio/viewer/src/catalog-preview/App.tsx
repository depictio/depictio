/**
 * Catalog-preview app shell: switches between the Gallery (all outputs on one
 * page) and a single output's detail view. The CLI decides the landing view via
 * `initialOutputId` — `catalog gallery` leaves it null (grid first), `catalog
 * preview <id>` sets it (straight into detail). Both embed the same payload
 * schema, so this is the only place that branches.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Gallery from './Gallery';
import OutputView from './OutputView';
import type { CatalogGlobal, OutputEntry } from './shared';

/** Read render_id from the URL hash (#render_id=...) — works inside an iframe
 *  without any backend-side injection, so no backend restart required. */
function readHashRenderId(): string | null {
  const m = window.location.hash.match(/[#&]render_id=([^&]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Read the selected output id from the URL hash (#output=...). */
function readHashOutputId(): string | null {
  const m = window.location.hash.match(/[#&]output=([^&]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

const CatalogApp: React.FC<{ g: CatalogGlobal }> = ({ g }) => {
  const tools = g.tools || [];
  const totalOutputs = useMemo(() => tools.reduce((n, t) => n + t.outputs.length, 0), [tools]);
  const [selected, setSelected] = useState<string | null>(
    readHashOutputId() ?? g.initialOutputId ?? null,
  );

  // Hash takes priority over injected value (works without backend restart).
  const renderId = readHashRenderId() ?? g.initialRenderId ?? null;

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

  const entry: OutputEntry | undefined = useMemo(() => {
    if (!selected) return undefined;
    for (const t of tools) {
      const found = t.outputs.find((o) => o.output.id === selected);
      if (found) return found;
    }
    return undefined;
  }, [selected, tools]);

  if (entry) {
    // Hide "back to catalog" when there's nothing to go back to (single preview).
    const onBack = totalOutputs > 1 ? () => navigate(null) : undefined;
    return <OutputView entry={entry} onBack={onBack} theme={g.theme} renderId={renderId} />;
  }
  return <Gallery tools={tools} onOpen={navigate} theme={g.theme} />;
};

export default CatalogApp;

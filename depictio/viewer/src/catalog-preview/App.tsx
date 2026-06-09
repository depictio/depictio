/**
 * Catalog-preview app shell: switches between the Gallery (all outputs on one
 * page) and a single output's detail view. The CLI decides the landing view via
 * `initialOutputId` — `catalog gallery` leaves it null (grid first), `catalog
 * preview <id>` sets it (straight into detail). Both embed the same payload
 * schema, so this is the only place that branches.
 */
import React, { useMemo, useState } from 'react';
import Gallery from './Gallery';
import OutputView from './OutputView';
import type { CatalogGlobal, OutputEntry } from './shared';

const CatalogApp: React.FC<{ g: CatalogGlobal }> = ({ g }) => {
  const tools = g.tools || [];
  const totalOutputs = useMemo(() => tools.reduce((n, t) => n + t.outputs.length, 0), [tools]);
  const [selected, setSelected] = useState<string | null>(g.initialOutputId ?? null);

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
    const onBack = totalOutputs > 1 ? () => setSelected(null) : undefined;
    return <OutputView entry={entry} onBack={onBack} theme={g.theme} />;
  }
  return <Gallery tools={tools} onOpen={setSelected} theme={g.theme} />;
};

export default CatalogApp;

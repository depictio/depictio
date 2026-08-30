import React from 'react';

import type { InteractiveFilter } from '../../api';
import { panelFilters } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import { AdvancedVizExtrasContext, AdvancedVizExtrasProvider } from './AdvancedVizExtras';
import type { AdvancedVizExtrasPayload } from './AdvancedVizExtras';

/**
 * "Split" for a component whose marks are aggregates.
 *
 * A scatter can be split after the fact, by dealing its points into panels —
 * that is `splitFigureByGroups`, and it works because every point is one row.
 * A sunburst wedge, a stacked taxonomy bar, an UpSet intersection and a
 * volcano's own summary rows are not one row each: they are already sums, and
 * no amount of cutting the finished figure apart recovers which group each
 * summand came from.
 *
 * So this splits one level earlier. Each panel is the *whole component*, built
 * from that group's rows alone, through the ordinary fetch path with the
 * group's filter appended. The renderer is handed nothing new and needs to
 * know nothing: a per-group sunburst is a sunburst of that group's rows. That
 * makes every `viz_kind` splittable, including the ones the server computes.
 *
 * What it costs is one fetch per panel, which is why `MAX_PANELS` is low: past
 * a handful of groups small multiples stop being readable anyway.
 */

/** Above this many groups the split is refused and the component renders whole.
 *  One fetch per panel, and small multiples stop being legible well before
 *  this. Deliberately well under the server's `MAX_FACET_CATEGORIES` (12),
 *  which faces a single query rather than one per panel. */
export const MAX_PANELS = 6;

/** Cells per row before wrapping. Past this a panel is too narrow to read. */
export const PANEL_COL_WRAP = 3;

/** Kinds that refuse the split and take grouping as colour instead.
 *
 * An ordination is the whole case: it means one thing only, where each sample
 * falls relative to every other sample in one shared space. Dealing that cloud
 * into per-group panels answers a question nobody asked of it, and each panel
 * would in fact be a *different* ordination, recomputed from its group's rows
 * alone — the axes would not even be comparable. Colour says the same thing
 * without either cost. */
const NO_SPLIT_KINDS = new Set(['embedding']);

export interface SplitPanelsProps {
  /** The cells to draw. Where they came from — saved groups, a column's
   *  values, or the cross of two dimensions — is `splitPanels`' business, not
   *  this component's. */
  panels: PanelSpec[];
  filters: InteractiveFilter[];
  /** Builds one panel. `key` distinguishes the instances for React. */
  renderPanel: (filters: InteractiveFilter[], key: string) => React.ReactNode;
  /** Raised when every panel came back holding the same data, i.e. the
   *  constraints found nothing to narrow on this collection. The caller then
   *  renders the component whole. */
  onIneffective: () => void;
}

/** A cheap fingerprint of a panel's fetched rows, enough to tell "the filter
 *  narrowed this" from "every panel got the same frame". Sampled rather than
 *  hashed whole: the two cases differ in row count or in the very first
 *  values, and a frame can be large. */
function rowsSignature(rows: Record<string, unknown[]> | undefined): string | null {
  if (!rows) return null;
  const columns = Object.keys(rows);
  if (columns.length === 0) return '0';
  const first = rows[columns[0]] ?? [];
  const parts: string[] = [String(columns.length), String(first.length)];
  for (const column of columns.slice(0, 3)) {
    const values = rows[column] ?? [];
    parts.push(String(values[0]), String(values[values.length - 1]));
    let acc = 0;
    for (let i = 0; i < values.length; i += 17) acc = (acc * 31 + String(values[i]).length) | 0;
    parts.push(String(acc));
  }
  return parts.join('|');
}

/** Whether the dashboard is asking for this split, and it is small enough to
 *  honour. Read by the dispatch before it decides how to render. */
export function shouldSplitIntoPanels(panels: PanelSpec[], vizKind: string): boolean {
  if (NO_SPLIT_KINDS.has(vizKind)) return false;
  return panels.length > 1 && panels.length <= MAX_PANELS;
}

const SplitPanels: React.FC<SplitPanelsProps> = ({
  panels,
  filters,
  renderPanel,
  onIneffective,
}) => {
  // Only the first panel's settings and data popovers reach the chrome: they
  // are the same controls on every panel, and N copies of one popover in one
  // tile's action bar is noise, not choice.
  const outerPublish = React.useContext(AdvancedVizExtrasContext);
  // Every panel is still listened to, for its data alone. Whether the split
  // said anything is only knowable once the panels have their rows: the
  // filter may name a column this collection reaches through a link the
  // browser cannot see, so the honest test is what actually came back.
  const signatures = React.useRef<Array<string | null>>([]);
  const settled = React.useRef(false);

  const publisherFor = React.useCallback(
    (index: number) => (payload: AdvancedVizExtrasPayload | null) => {
      if (index === 0) outerPublish?.(payload);
      if (settled.current) return;
      signatures.current[index] = rowsSignature(payload?.data?.rows);
      const reported = signatures.current;
      if (reported.length < panels.length) return;
      if (reported.some((s) => s == null)) return;
      if (reported.every((s) => s === reported[0])) {
        settled.current = true;
        onIneffective();
      }
    },
    [outerPublish, onIneffective, panels.length],
  );

  React.useEffect(() => {
    signatures.current = [];
    settled.current = false;
  }, [panels.length, filters]);

  if (panels.length === 0) return null;

  // A flat list of cells, wrapped. Two dimensions arrive already crossed, so
  // the wrap is what gives the grid back its shape without this component
  // needing to know how many dimensions produced the cells.
  const columns = Math.min(panels.length, PANEL_COL_WRAP);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gridTemplateRows: `repeat(${Math.ceil(panels.length / columns)}, minmax(0, 1fr))`,
        gap: 8,
        width: '100%',
        height: '100%',
        minHeight: 0,
      }}
    >
      {panels.map((panel, i) => (
        <div
          key={panel.name}
          style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: panel.color ?? 'inherit',
              textAlign: 'center',
              paddingBottom: 2,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={panel.name}
          >
            {panel.name}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <AdvancedVizExtrasProvider onChange={publisherFor(i)}>
              {renderPanel(panelFilters(filters, panel), panel.name)}
            </AdvancedVizExtrasProvider>
          </div>
        </div>
      ))}
    </div>
  );
};

export default SplitPanels;

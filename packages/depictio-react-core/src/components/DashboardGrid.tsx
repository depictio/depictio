import React from 'react';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import { StoredMetadata, InteractiveFilter } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface DashboardGridProps {
  dashboardId: string;
  metadataList: StoredMetadata[];
  layoutData?: unknown;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Precomputed card values keyed by component index. */
  cardValues?: Record<string, unknown>;
  /** True while the bulk compute is pending. */
  cardValuesLoading?: boolean;
}

/**
 * Renders the dashboard component tree inside react-grid-layout. Depictio's
 * stored_layout_data uses dash-dynamic-grid-layout's format, which is a thin
 * wrapper over react-grid-layout — same {i, x, y, w, h} shape works directly.
 *
 * When stored_layout_data is absent, components are auto-placed in a 2-column
 * flow to give the viewer SOMETHING reasonable (matches Dash's fallback).
 */
const DashboardGrid: React.FC<DashboardGridProps> = ({
  metadataList,
  layoutData,
  filters,
  onFilterChange,
  cardValues,
  cardValuesLoading,
}) => {
  const layouts = normalizeLayout(metadataList, layoutData);
  const containerWidth = typeof window !== 'undefined' ? window.innerWidth - 40 : 1200;

  return (
    <GridLayout
      className="layout"
      layout={layouts}
      cols={12}
      rowHeight={50}
      width={containerWidth}
      margin={[12, 12]}
      containerPadding={[12, 12]}
      isDraggable={false}
      isResizable={false}
      compactType="vertical"
    >
      {metadataList.map((m) => (
        <div key={m.index} style={{ overflow: 'hidden' }}>
          <ComponentRenderer
            metadata={m}
            filters={filters}
            onFilterChange={onFilterChange}
            cardValue={cardValues?.[m.index]}
            cardLoading={cardValuesLoading}
          />
        </div>
      ))}
    </GridLayout>
  );
};

export default DashboardGrid;

function normalizeLayout(
  metadataList: StoredMetadata[],
  layoutData: unknown,
): Layout[] {
  // Dash stores layouts as a list of { i: "box-<index>", x, y, w, h } OR as
  // { breakpoint: [...] } keyed dict. Try both shapes.
  const items = extractLayoutItems(layoutData);
  if (items.length > 0) {
    const indexSet = new Set(metadataList.map((m) => m.index));
    const matched = items
      .map((it) => ({
        ...it,
        i: stripBoxPrefix(it.i),
      }))
      .filter((it) => indexSet.has(it.i));
    if (matched.length === metadataList.length) return matched;
  }

  // Fallback: 2-column auto-flow, each item 6w × 4h
  return metadataList.map((m, idx) => ({
    i: m.index,
    x: (idx % 2) * 6,
    y: Math.floor(idx / 2) * 4,
    w: 6,
    h: 4,
    static: true,
  }));
}

function extractLayoutItems(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (i): i is Layout =>
        i && typeof i === 'object' && 'i' in i && 'x' in i && 'y' in i,
    );
  }
  if (typeof layoutData === 'object') {
    // dict keyed by breakpoint — take 'lg' or the first key
    const obj = layoutData as Record<string, unknown>;
    const candidateKey =
      'lg' in obj
        ? 'lg'
        : Object.keys(obj).find((k) => Array.isArray(obj[k])) || '';
    if (candidateKey && Array.isArray(obj[candidateKey])) {
      return (obj[candidateKey] as Layout[]).filter(
        (i) => i && typeof i === 'object' && 'i' in i,
      );
    }
  }
  return [];
}

function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
}

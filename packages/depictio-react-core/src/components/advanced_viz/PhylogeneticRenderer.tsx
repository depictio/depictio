import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import AdvancedVizPlot from './AdvancedVizPlot';

import {
  fetchAdvancedVizData,
  fetchPhylogenyNewick,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { stableColorMap } from '../../colors';
import { filtersExcludingOwn } from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';
import { ladderise, parseNewick, type PhyloNode, type PhyloTree, toNewick } from './phylo/newick';
import { computeLayout, descendants, type Layout } from './phylo/layout';
import {
  buildTreeSelectionFilter,
  collectSubtreeTaxa,
  findSubtreeRootByLeafSet,
  treeSelectionValues,
} from './phylo/subtree';

interface PhylogeneticConfig {
  tree_wf_id: string;
  tree_dc_id: string;
  metadata_wf_id?: string | null;
  metadata_dc_id?: string | null;
  taxon_col?: string;
  color_col?: string | null;
  label_col?: string | null;
  /** Extra metadata columns to fetch alongside color_col / label_col, so
   *  they show up in the "Colour by" Select. Use for taxonomic ranks on
   *  ASV trees (Kingdom / Phylum / Class / Order / Family / Genus / Species). */
  extra_color_cols?: string[] | null;
  /** Per-column palette overrides for the "Colour by" selector. Shape:
   *  ``{column_name: {category_value: hex}}``. Lets dashboards pin domain
   *  palettes (e.g. dominant_habitat → Set1) consistently across tiles. */
  category_palettes?: Record<string, Record<string, string>> | null;
  default_layout?: Layout;
  ladderize?: boolean;
  show_metadata_strip?: boolean;
  show_branch_lengths?: boolean;
  show_internal_labels?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PhylogeneticConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Receives a `tree_selection` filter when the user filters the dashboard
   *  to a selected clade. Pass `value: []` to clear. The parent merges by
   *  `(index, source)`. Absent in read-only hosts — the filter button hides,
   *  clade highlight and export still work. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Muted publication-friendly palette for categorical tip colouring.
const PALETTE = [
  '#4C72B0',
  '#DD8452',
  '#55A868',
  '#C44E52',
  '#8172B3',
  '#937860',
  '#DA8BC3',
  '#8C8C8C',
];

const LAYOUTS: Array<{ value: Layout; label: string }> = [
  { value: 'rectangular', label: 'Rect' },
  { value: 'circular', label: 'Circ' },
  { value: 'radial', label: 'Radial' },
  { value: 'diagonal', label: 'Diag' },
  { value: 'hierarchical', label: 'Hier' },
];

const PhylogeneticRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as PhylogeneticConfig;
  const isDark = colorScheme === 'dark';

  // ---- Tier-2 (intra-viz) controls ----------------------------------------
  const [layout, setLayout] = useState<Layout>(config.default_layout ?? 'rectangular');
  const [doLadderise, setDoLadderise] = useState<boolean>(config.ladderize ?? true);
  const [showStrip, setShowStrip] = useState<boolean>(config.show_metadata_strip ?? true);
  const [showBranchLengths, setShowBranchLengths] = useState<boolean>(
    config.show_branch_lengths ?? false,
  );
  const [search, setSearch] = useState<string>('');
  const [colorCol, setColorCol] = useState<string | null>(config.color_col ?? null);
  const [highlightedRootId, setHighlightedRootId] = useState<number | null>(null);
  // Zoom/pan is off by default: Plotly's drag-to-zoom-box steals every drag
  // and there was no way back except double-click. Toggled on, drag pans and
  // the scroll wheel zooms.
  const [zoomEnabled, setZoomEnabled] = useState<boolean>(false);
  // Bumping this changes `uirevision`, discarding the user's zoom/pan and
  // re-applying the fitted axis ranges ("Reset view").
  const [viewEpoch, setViewEpoch] = useState<number>(0);
  // Viewport captured when zoom is toggled off. Toggling flips the Plotly
  // `config` (scrollZoom), which forces a plot rebuild that would snap back
  // to the fitted ranges — baking the captured ranges into the layout keeps
  // the view frozen instead. Cleared by "Reset view" and on layout switch.
  const [frozenRanges, setFrozenRanges] = useState<{ x: number[]; y: number[] } | null>(null);
  // Stable universe of distinct values for the colour column — keeps tip
  // colours invariant when the user filters down to a subset.
  const [colorUniverse, setColorUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    const metaDc = config.metadata_dc_id;
    if (!metaDc || !colorCol) {
      setColorUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metaDc, colorCol)
      .then((values) => {
        if (!cancelled) setColorUniverse(values);
      })
      .catch(() => {
        /* best-effort */
      });
    return () => {
      cancelled = true;
    };
  }, [config.metadata_dc_id, colorCol]);

  // ---- Data fetching ------------------------------------------------------
  const [newick, setNewick] = useState<string | null>(null);
  const [meta, setMeta] = useState<Record<string, unknown[]> | null>(null);
  const [metaCols, setMetaCols] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Tip metadata is served whole; past `advanced_viz_no_sample_max_rows` the
  // server samples it, which means tips go missing rather than blur.
  const [estimated, setEstimated] = useState(false);

  // The tree's own subtree filter is stripped before fetching: it must keep
  // showing the whole tree (its selection reads as the pink highlight, not as
  // ghosting), and a self-applied filter would make widening the selection
  // impossible.
  const fetchFilters = filtersExcludingOwn(filters, metadata.index, 'tree_selection');

  useEffect(() => {
    if (!config.tree_dc_id) {
      setError('Phylogenetic: missing tree DC binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    // 1) Newick tree (raw text).
    const treeP = fetchPhylogenyNewick(config.tree_dc_id);

    // 2) Metadata table (optional). Project all columns mentioned in the
    //    config + any user-toggleable colour columns we know about.
    const taxonCol = config.taxon_col || 'taxon';
    const wantedCols: string[] = [taxonCol];
    if (config.color_col) wantedCols.push(config.color_col);
    if (config.label_col) wantedCols.push(config.label_col);
    // Extra columns surfaced as alternative colour-by options in the
    // controls popover. Typical use: taxonomic ranks for an ASV tree
    // (Kingdom / Phylum / Class / …) so the user can re-colour the tips
    // at a different level without reloading the page.
    if (Array.isArray(config.extra_color_cols)) {
      for (const c of config.extra_color_cols) if (c) wantedCols.push(c);
    }
    const metaP =
      config.metadata_wf_id && config.metadata_dc_id
        ? fetchAdvancedVizData({
            wfId: config.metadata_wf_id,
            dcId: config.metadata_dc_id,
            columns: Array.from(new Set(wantedCols)),
            filters: fetchFilters,
            vizKind: 'phylogenetic',
          })
        : Promise.resolve(null);

    Promise.all([treeP, metaP])
      .then(([nw, metaRes]) => {
        if (cancelled) return;
        setNewick(nw);
        if (metaRes) {
          setMeta(metaRes.rows);
          setMetaCols(metaRes.columns);
          // A sampled tip-metadata table is missing tips, not merely coarser:
          // the ones it drops render uncoloured with no label.
          setEstimated(Boolean(metaRes.sampling?.degraded));
        } else {
          setMeta(null);
          setMetaCols([]);
          setEstimated(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [config.tree_dc_id, config.metadata_wf_id, config.metadata_dc_id, JSON.stringify(fetchFilters), refreshTick]);

  // ---- Tree object (memo) -------------------------------------------------
  const tree = useMemo<PhyloTree | null>(() => {
    if (!newick) return null;
    try {
      const t = parseNewick(newick);
      if (doLadderise) ladderise(t, true);
      return t;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, [newick, doLadderise]);

  // ---- Tip metadata lookup -----------------------------------------------
  const tipMeta = useMemo<Map<string, Record<string, unknown>>>(() => {
    const out = new Map<string, Record<string, unknown>>();
    if (!meta) return out;
    const taxonCol = config.taxon_col || 'taxon';
    const taxa = (meta[taxonCol] || []) as unknown[];
    for (let i = 0; i < taxa.length; i++) {
      const tax = String(taxa[i] ?? '');
      const row: Record<string, unknown> = {};
      for (const c of metaCols) row[c] = (meta[c] || [])[i];
      out.set(tax, row);
    }
    return out;
  }, [meta, metaCols, config.taxon_col]);

  // ---- Tip colouring ------------------------------------------------------
  const tipColors = useMemo<{ colorByTip: Map<string, string>; categories: string[] }>(() => {
    const colorByTip = new Map<string, string>();
    if (!tree) return { colorByTip, categories: [] };
    if (!colorCol || !meta) {
      for (const leaf of tree.leaves) colorByTip.set(leaf.name ?? '', PALETTE[0]);
      return { colorByTip, categories: [] };
    }
    // Build categorical palette keyed on the FULL distinct-value universe
    // when available — filter changes don't shift colours then. Falls back to
    // the visible tree's unique values when the unique-values fetch hasn't
    // responded yet.
    const uniqueValues: string[] = [];
    for (const leaf of tree.leaves) {
      const row = tipMeta.get(leaf.name ?? '');
      const v = row ? String(row[colorCol] ?? '—') : '—';
      if (!uniqueValues.includes(v)) uniqueValues.push(v);
    }
    uniqueValues.sort();
    // Per-column palette override pulled from the dashboard config — keeps
    // habitat-style category colours stable across PCoA / UpSet / heatmap /
    // phylogeny tiles. Falls back to PALETTE-index assignment otherwise.
    const palettesByCol = config.category_palettes || {};
    const colourSource = stableColorMap(
      colorUniverse ?? uniqueValues,
      PALETTE,
      colorCol ? palettesByCol[colorCol] || null : null,
    );
    for (const leaf of tree.leaves) {
      const row = tipMeta.get(leaf.name ?? '');
      const v = row ? String(row[colorCol] ?? '—') : '—';
      colorByTip.set(leaf.name ?? '', colourSource.get(v));
    }
    return { colorByTip, categories: uniqueValues };
  }, [tree, colorCol, meta, tipMeta, colorUniverse]);

  // ---- Highlighted subtree (clade selection) ------------------------------
  const highlightedIds = useMemo<Set<number>>(() => {
    if (!tree || highlightedRootId == null) return new Set();
    const root = tree.nodes.find((n) => n.id === highlightedRootId) ?? null;
    if (!root) return new Set();
    return new Set(descendants(root).map((n) => n.id));
  }, [tree, highlightedRootId]);

  // ---- Subtree selection → dashboard filter -------------------------------
  const selectionTaxa = useMemo<string[]>(
    () => (tree && highlightedRootId != null ? collectSubtreeTaxa(tree, highlightedRootId) : []),
    [tree, highlightedRootId],
  );
  const selectionName = useMemo<string | null>(() => {
    if (!tree || highlightedRootId == null) return null;
    return tree.nodes.find((n) => n.id === highlightedRootId)?.name ?? null;
  }, [tree, highlightedRootId]);
  // Own emitted filter, read back out of the filter list (the only record of
  // it — see `fetchFilters` above). Also drives restore-after-remount.
  const ownFilterValues = useMemo<string[]>(
    () => treeSelectionValues(filters, metadata.index),
    [filters, metadata.index],
  );
  const filterActive = ownFilterValues.length > 0;
  // Whether the emitted filter matches the current highlight — when the user
  // moves the highlight to another clade while a filter is active, the button
  // flips back to "Filter to subtree" and emitting replaces the old entry.
  const selectionMatchesFilter = useMemo<boolean>(() => {
    if (!filterActive || selectionTaxa.length !== ownFilterValues.length) return false;
    const own = new Set(ownFilterValues);
    return selectionTaxa.every((t) => own.has(t));
  }, [filterActive, selectionTaxa, ownFilterValues]);
  const canFilter = Boolean(onFilterChange && config.metadata_dc_id);

  const emitTreeFilter = (values: string[]) => {
    if (!onFilterChange || !config.metadata_dc_id) return;
    onFilterChange(
      buildTreeSelectionFilter(
        metadata.index,
        config.metadata_dc_id,
        config.taxon_col || 'taxon',
        values,
      ),
    );
  };

  const clearSelection = () => {
    setHighlightedRootId(null);
    if (filterActive) emitTreeFilter([]);
  };

  // Node ids are reassigned on every parse, so a highlight can't survive a
  // change of the newick text itself…
  useEffect(() => {
    setHighlightedRootId(null);
  }, [newick]);
  // …instead the selection is re-derived by taxon names from the emitted
  // filter — which also restores it after a tab switch remounts the
  // component. Functional update so a highlight the user moved to another
  // clade isn't snapped back while the old filter is still in the list.
  useEffect(() => {
    if (!tree || ownFilterValues.length === 0) return;
    setHighlightedRootId((prev) => (prev != null ? prev : findSubtreeRootByLeafSet(tree, ownFilterValues)));
  }, [tree, JSON.stringify(ownFilterValues)]);

  // ---- Filter-derived "tips in scope" set --------------------------------
  // Sidebar / global filters narrow the metadata DC; any leaf whose taxon
  // isn't in the filtered metadata gets dimmed (smaller marker, ghost edge).
  // No filters bound → everything is "in scope" so the tree renders normally.
  const tipsInScope = useMemo<Set<string> | null>(() => {
    if (!meta) return null;
    const taxonCol = config.taxon_col || 'taxon';
    const taxa = (meta[taxonCol] || []) as unknown[];
    // If the filtered metadata returns the FULL set there's no filter applied;
    // a null result skips the dimming logic.
    const inScope = new Set(taxa.map((v) => String(v ?? '')));
    return inScope;
  }, [meta, config.taxon_col]);

  const isInScope = (taxonName: string): boolean => {
    if (!tipsInScope) return true;
    return tipsInScope.has(taxonName);
  };

  // ---- Plotly figure ------------------------------------------------------
  const figure = useMemo(() => {
    if (!tree) return null;
    const result = computeLayout(tree, layout);
    const traces: any[] = [];

    // For each internal node, determine if any descendant leaf is in scope —
    // that edge stays "solid"; otherwise the edge is rendered as ghost.
    const subtreeInScope = new Map<number, boolean>();
    function visit(n: PhyloNode): boolean {
      if (n.children.length === 0) {
        const ok = isInScope(n.name ?? '');
        subtreeInScope.set(n.id, ok);
        return ok;
      }
      let any = false;
      for (const c of n.children) if (visit(c)) any = true;
      subtreeInScope.set(n.id, any);
      return any;
    }
    visit(tree.root);

    // Edges: three traces — ghost (out-of-scope), base (in scope), highlight
    // (selected subtree). Drawn in that z-order.
    const baseEdgeColour = isDark ? 'rgba(220,220,220,0.65)' : 'rgba(40,40,40,0.65)';
    const ghostEdgeColour = isDark ? 'rgba(180,180,180,0.18)' : 'rgba(60,60,60,0.15)';
    const hiEdgeColour = '#E64980';

    const ghostXs: (number | null)[] = [];
    const ghostYs: (number | null)[] = [];
    const edgeXs: (number | null)[] = [];
    const edgeYs: (number | null)[] = [];
    const hiEdgeXs: (number | null)[] = [];
    const hiEdgeYs: (number | null)[] = [];
    for (const e of result.edges) {
      const isHi = highlightedIds.has(e.to.id);
      const isGhost = !subtreeInScope.get(e.to.id);
      const tgtXs = isHi ? hiEdgeXs : isGhost ? ghostXs : edgeXs;
      const tgtYs = isHi ? hiEdgeYs : isGhost ? ghostYs : edgeYs;
      for (const [x, y] of e.pts) {
        tgtXs.push(x);
        tgtYs.push(y);
      }
      tgtXs.push(null);
      tgtYs.push(null);
    }

    if (ghostXs.length > 0) {
      traces.push({
        type: 'scattergl' as const,
        mode: 'lines' as const,
        x: ghostXs,
        y: ghostYs,
        hoverinfo: 'skip',
        line: { color: ghostEdgeColour, width: 1 },
        showlegend: false,
      });
    }
    traces.push({
      type: 'scattergl' as const,
      mode: 'lines' as const,
      x: edgeXs,
      y: edgeYs,
      hoverinfo: 'skip',
      line: { color: baseEdgeColour, width: 1.4 },
      showlegend: false,
    });
    if (hiEdgeXs.length > 0) {
      traces.push({
        type: 'scattergl' as const,
        mode: 'lines' as const,
        x: hiEdgeXs,
        y: hiEdgeYs,
        hoverinfo: 'skip',
        line: { color: hiEdgeColour, width: 2.4 },
        showlegend: false,
      });
    }

    // Branch-length annotations (when toggle is on, and only for layouts
    // where edges have well-defined midpoints in screen space).
    const branchLengthAnnotations: any[] = [];
    if (showBranchLengths && (layout === 'rectangular' || layout === 'diagonal' || layout === 'hierarchical')) {
      for (const e of result.edges) {
        const len = e.to.branchLength;
        if (!Number.isFinite(len)) continue;
        // Rectangular polyline: pts[0]=parent, pts[1]=elbow, pts[2]=child.
        // Use the horizontal segment between elbow and child for label position.
        const pts = e.pts;
        const last = pts[pts.length - 1];
        const prev = pts[pts.length - 2] ?? pts[0];
        const mx = (prev[0] + last[0]) / 2;
        const my = (prev[1] + last[1]) / 2;
        branchLengthAnnotations.push({
          x: mx,
          y: my,
          text: len.toFixed(3),
          showarrow: false,
          font: { size: 9, color: isDark ? '#ced4da' : '#495057' },
          yshift: 8,
          bgcolor: 'rgba(0,0,0,0)',
        });
      }
    }

    // Tips.
    const tipXs: number[] = [];
    const tipYs: number[] = [];
    const tipLabels: string[] = [];
    const tipColours: string[] = [];
    const tipSizes: number[] = [];
    const tipBorders: string[] = [];
    const tipOpacities: number[] = [];
    const tipIds: number[] = [];
    // Per-tip customdata: [internal_id, ...metadata_values]. We thread the
    // metadata columns through Plotly's customdata so the hovertemplate can
    // pick them up by index without per-trace string interpolation.
    const tipCustomdata: (number | string)[][] = [];
    // Hover columns: every metadata column except the taxon (already in
    // %{text}). Order matters because hovertemplate references customdata
    // by integer index — see the template assembly below.
    const taxonCol = config.taxon_col || 'taxon';
    const hoverCols = metaCols.filter((c) => c !== taxonCol);

    const searchLc = search.trim().toLowerCase();
    for (const leaf of tree.leaves) {
      const name = leaf.name ?? '';
      const inScope = isInScope(name);
      tipXs.push(leaf.x!);
      tipYs.push(leaf.y!);
      tipLabels.push(name);
      tipIds.push(leaf.id);
      tipColours.push(tipColors.colorByTip.get(name) ?? PALETTE[0]);
      const isHi = highlightedIds.has(leaf.id);
      const isSearchMatch = searchLc.length > 0 && name.toLowerCase().includes(searchLc);
      tipSizes.push(isSearchMatch ? 13 : isHi ? 10 : inScope ? 8 : 5);
      tipBorders.push(
        isSearchMatch ? '#FAB005' : isHi ? '#E64980' : isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.4)',
      );
      tipOpacities.push(inScope ? 1 : 0.25);
      // customdata: [leaf.id, ...meta values for each hoverCol]. Falls back to
      // '—' so the hover line stays aligned even when a rank isn't resolved.
      const row = tipMeta.get(name) || {};
      const customRow: (number | string)[] = [leaf.id];
      for (const c of hoverCols) {
        const v = row[c];
        customRow.push(v == null || v === '' ? '—' : String(v));
      }
      tipCustomdata.push(customRow);
    }

    // For dense trees the tip-label text becomes unreadable noise (ASV hash
    // ids overlap each other). Threshold matches the QIIME2 q2-emperor
    // default: tip text only when there are <= 80 tips. Hover still shows
    // the full name. Always-text on small trees; markers-only on big ones.
    const tipTextMode = tree.leaves.length <= 80 ? 'markers+text' : 'markers';
    // scattergl renders 10x+ faster for large tip counts and keeps pan/zoom
    // responsive on 10k+ tip trees. Plain scatter is preferable for small
    // trees because it supports text-mode rendering and richer hover boxes
    // out of the box, but at scale the WebGL trade-off is the right call.
    const tipTraceType = tree.leaves.length > 500 ? 'scattergl' : 'scatter';

    // Build a hover template that shows the taxon (text) followed by each
    // metadata rank on its own line. Index [0] is leaf.id (used by the click
    // handler); metadata starts at index [1]. When no metadata columns exist
    // the template falls back to just the tip name.
    const hoverLines = hoverCols.map(
      (col, i) => `<b>${col}</b>: %{customdata[${i + 1}]}`,
    );
    const hoverTpl =
      hoverLines.length > 0
        ? `<b>%{text}</b><br>${hoverLines.join('<br>')}<extra></extra>`
        : '%{text}<extra></extra>';

    traces.push({
      type: tipTraceType,
      mode: tipTextMode,
      x: tipXs,
      y: tipYs,
      text: tipLabels,
      customdata: tipCustomdata,
      textposition: layout === 'rectangular' || layout === 'diagonal' ? 'middle right' : 'top center',
      textfont: { size: 10, color: isDark ? '#e9ecef' : '#212529' },
      hovertemplate: hoverTpl,
      marker: {
        size: tipSizes,
        color: tipColours,
        line: { color: tipBorders, width: 1 },
        opacity: tipOpacities,
      },
      showlegend: false,
    });

    // Internal-node click targets — invisible markers so the user can
    // click an internal node to highlight its subtree.
    const internalXs: number[] = [];
    const internalYs: number[] = [];
    const internalIds: number[] = [];
    for (const n of tree.nodes) {
      if (n.children.length === 0) continue;
      internalXs.push(n.x!);
      internalYs.push(n.y!);
      internalIds.push(n.id);
    }
    traces.push({
      type: 'scatter' as const,
      mode: 'markers',
      x: internalXs,
      y: internalYs,
      customdata: internalIds,
      hovertemplate: 'click to highlight subtree<extra></extra>',
      marker: { size: 6, color: 'rgba(0,0,0,0)', line: { width: 0 } },
      showlegend: false,
    });

    // Categorical legend (renders separately below the controls — using
    // plotly's legend would cramp the tree). We compute it here and
    // surface as React below via `tipColors.categories`.

    // Equal aspect ratio for circular/radial. Rectangular/hierarchical/
    // diagonal benefit from auto-scaling so leaf labels don't squash.
    const square = layout === 'circular' || layout === 'radial';

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 16, r: 200, t: 8, b: 16 }, // r room for leaf labels
        xaxis: { visible: false, range: [result.bbox.minX - 0.05, result.bbox.maxX + 0.5] },
        yaxis: {
          visible: false,
          scaleanchor: square ? 'x' : undefined,
          range: [result.bbox.minY - 0.5, result.bbox.maxY + 0.5],
        },
        showlegend: false,
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
        annotations: branchLengthAnnotations,
      },
    };
  }, [tree, layout, isDark, tipColors, highlightedIds, search, showBranchLengths, tipsInScope]);

  // Zoom/pan knobs live outside the heavy figure memo so toggling them never
  // recomputes the tree layout. `uirevision` keeps the user's viewport across
  // highlight / search / filter recomputes (the memo above hard-sets axis
  // ranges on every run and would otherwise reset the view each time); it is
  // keyed on the layout kind — switching Rect→Circ resets cleanly — and on
  // `viewEpoch` for the explicit "Reset view" action. Deliberately NOT keyed
  // on `zoomEnabled`: toggling zoom off freezes the current view rather than
  // resetting it.
  const plotLayout = useMemo(() => {
    if (!figure) return null;
    return {
      ...figure.layout,
      // Fresh axis objects AND range arrays each time: Plotly's pan handler
      // mutates `range` in place on the layout it is handed, and a mutated
      // range leaking back into the memoized figure both breaks "Reset view"
      // (it would re-apply the panned range) and desyncs uirevision's idea of
      // what the supplied range is (snapping the view on the next recompute).
      xaxis: {
        ...figure.layout.xaxis,
        range: frozenRanges ? [...frozenRanges.x] : [...figure.layout.xaxis.range],
      },
      yaxis: {
        ...figure.layout.yaxis,
        range: frozenRanges ? [...frozenRanges.y] : [...figure.layout.yaxis.range],
      },
      dragmode: zoomEnabled ? ('pan' as const) : (false as const),
      uirevision: `phylo:${layout}:${viewEpoch}`,
    };
  }, [figure, zoomEnabled, layout, viewEpoch, frozenRanges]);

  // Scroll-zoom is opt-in via the toolbar toggle — always-on wheel capture
  // steals page scroll (see RarefactionRenderer for the rationale). The hover
  // modebar is hidden: the toolbar is the single control point.
  const plotConfig = useMemo(
    () => ({
      displaylogo: false,
      responsive: true,
      displayModeBar: false,
      scrollZoom: zoomEnabled,
      doubleClick: zoomEnabled ? ('reset' as const) : (false as const),
    }),
    [zoomEnabled],
  );

  // Unique div id so the toggle handler can read the live viewport off the
  // Plotly graph div (react-plotly exposes no ref to it).
  const plotDivId = `phylo-plot-${metadata.index}`;

  const toggleZoom = () => {
    if (zoomEnabled) {
      // Turning zoom off — freeze whatever viewport the user is looking at.
      const gd = document.getElementById(plotDivId) as any;
      const xr = gd?._fullLayout?.xaxis?.range;
      const yr = gd?._fullLayout?.yaxis?.range;
      if (xr && yr) setFrozenRanges({ x: [...xr], y: [...yr] });
    }
    setZoomEnabled(!zoomEnabled);
  };

  const resetView = () => {
    setFrozenRanges(null);
    setViewEpoch((e) => e + 1);
  };

  // A different layout kind recomputes every coordinate — a frozen viewport
  // from the previous kind would show an arbitrary crop of the new one.
  useEffect(() => {
    setFrozenRanges(null);
  }, [layout]);

  // ---- Controls -----------------------------------------------------------
  const colorOptions: { value: string; label: string }[] = useMemo(() => {
    if (!metaCols || metaCols.length === 0) return [];
    const taxonCol = config.taxon_col || 'taxon';
    return metaCols.filter((c) => c !== taxonCol).map((c) => ({ value: c, label: c }));
  }, [metaCols, config.taxon_col]);

  const exportSelectedNewick = () => {
    if (!tree || highlightedRootId == null) return;
    const root = tree.nodes.find((n) => n.id === highlightedRootId);
    if (!root) return;
    const text = toNewick(root);
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${root.name ?? 'subtree'}.nwk`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const controls = (
    <Stack gap="xs">
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Mode
        </Text>
        <SegmentedControl
        size="xs"
        data={LAYOUTS}
        value={layout}
        onChange={(v) => setLayout(v as Layout)}
        fullWidth
      />
      </Stack>
      <TextInput
        size="xs"
        label="Search tip"
        placeholder="taxon name"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      {colorOptions.length > 0 ? (
        <Select
          size="xs"
          label="Colour by"
          value={colorCol}
          onChange={setColorCol}
          data={colorOptions}
          clearable
        />
      ) : null}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Ladderise
        </Text>
        <Switch
        size="xs"
        checked={doLadderise}
        onChange={(e) => setDoLadderise(e.currentTarget.checked)}
        label="Ladderise"
      />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Strip
        </Text>
        <Switch
        size="xs"
        checked={showStrip}
        onChange={(e) => setShowStrip(e.currentTarget.checked)}
        label="Metadata strip"
      />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Branch lengths
        </Text>
        <Switch
        size="xs"
        checked={showBranchLengths}
        onChange={(e) => setShowBranchLengths(e.currentTarget.checked)}
        label="Branch lengths"
      />
      </Stack>
    </Stack>
  );

  // ---- Always-visible toolbar (zoom/pan + subtree actions) ----------------
  // Rendered in the frame body: the `controls` stack above only reaches the
  // Settings popover, which is exactly why the old Clear/Export buttons went
  // unnoticed. Subtree actions appear only while a clade is selected.
  const toolbar = (
    <Group gap="xs" px="sm" pb={4} wrap="wrap" data-testid="phylo-toolbar">
      <Tooltip
        label={zoomEnabled ? 'Zoom on — scroll to zoom, drag to pan' : 'Enable zoom & pan'}
        withArrow
      >
        <ActionIcon
          size="sm"
          variant={zoomEnabled ? 'filled' : 'default'}
          aria-pressed={zoomEnabled}
          aria-label="Toggle zoom & pan"
          data-testid="phylo-zoom-toggle"
          onClick={toggleZoom}
        >
          <Icon icon="mdi:magnify-plus-outline" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Reset view" withArrow>
        <ActionIcon
          size="sm"
          variant="default"
          aria-label="Reset view"
          data-testid="phylo-reset-view"
          onClick={resetView}
        >
          <Icon icon="mdi:fit-to-screen" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
      {highlightedRootId != null ? (
        <>
          <Badge color="pink" variant="light" data-testid="phylo-selection-badge">
            {`${selectionName ?? 'clade'} · ${selectionTaxa.length} tips`}
          </Badge>
          {canFilter ? (
            <Button
              size="compact-xs"
              color="pink"
              variant={selectionMatchesFilter ? 'filled' : 'light'}
              data-testid="phylo-filter-subtree"
              onClick={() =>
                selectionMatchesFilter ? emitTreeFilter([]) : emitTreeFilter(selectionTaxa)
              }
            >
              {selectionMatchesFilter ? 'Filtered — clear' : 'Filter to subtree'}
            </Button>
          ) : null}
          <Button
            size="compact-xs"
            variant="subtle"
            color="pink"
            data-testid="phylo-export-newick"
            onClick={exportSelectedNewick}
          >
            Export .nwk
          </Button>
          <Tooltip label="Clear selection" withArrow>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="pink"
              aria-label="Clear subtree selection"
              data-testid="phylo-clear-selection"
              onClick={clearSelection}
            >
              <Icon icon="mdi:close" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
        </>
      ) : filterActive ? (
        // The filter is live but its clade no longer maps onto this tree
        // (renamed tips, changed topology) — keep it visible and escapable.
        <>
          <Badge color="pink" variant="light" data-testid="phylo-selection-badge">
            {`subtree filter · ${ownFilterValues.length} tips`}
          </Badge>
          <Tooltip label="Clear subtree filter" withArrow>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="pink"
              aria-label="Clear subtree filter"
              data-testid="phylo-clear-selection"
              onClick={clearSelection}
            >
              <Icon icon="mdi:close" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
        </>
      ) : null}
    </Group>
  );

  // ---- Categorical legend (rendered as Mantine badges below the chart) ---
  const legend =
    tipColors.categories.length > 0 ? (
      <Group gap={6} px="sm" pb={4} wrap="wrap">
        {tipColors.categories.map((cat) => (
          <Group gap={4} key={cat} wrap="nowrap">
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                // Pull from the same stable colour map as the tips so legend
              // swatches match what's painted on the tree (and stay stable
              // when the user filters down to a subset of categories).
              background: stableColorMap(
                colorUniverse ?? tipColors.categories,
                PALETTE,
                colorCol ? (config.category_palettes || {})[colorCol] || null : null,
              ).get(cat),
              }}
            />
            <span style={{ fontSize: 11 }}>{cat}</span>
          </Group>
        ))}
      </Group>
    ) : null;

  // ---- Plotly click handler — toggle subtree highlight on click.
  const onPlotClick = (event: any) => {
    const cd = event?.points?.[0]?.customdata;
    if (cd == null) return;
    // customdata is now an array [leaf.id, ...metadata]. The leaf id lives
    // at index 0; older internal-node traces still pass a bare number, so
    // accept either shape.
    const id = Array.isArray(cd) ? cd[0] : cd;
    if (id == null) return;
    if (id === highlightedRootId) {
      // Re-clicking the selected node deselects — and drops the subtree
      // filter with it, so a selection can't outlive its visible anchor.
      clearSelection();
    } else {
      // A different node only moves the highlight; filtering stays an
      // explicit toolbar action.
      setHighlightedRootId(id as number);
    }
  };

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Phylogeny'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={tree && tree.leaves.length === 0 ? 'Empty tree' : undefined}
      dataRows={meta ?? undefined}
      dataColumns={metaCols}
    >
      <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
        {toolbar}
        {legend}
        <div style={{ flex: '1 1 auto', minHeight: 0 }}>
          {figure && plotLayout ? (
            <AdvancedVizPlot
              divId={plotDivId}
              data={applyDataTheme(figure.data, isDark, theme) as any}
              layout={applyLayoutTheme(plotLayout as any, isDark, theme) as any}
              onClick={onPlotClick}
              useResizeHandler
              style={{ width: '100%', height: '100%' }}
              config={plotConfig as any}
            />
          ) : null}
        </div>
      </div>
    </AdvancedVizFrame>
  );
};

export default PhylogeneticRenderer;

import React, { useEffect, useMemo, useRef, useState } from 'react';
import Plotly from 'plotly.js';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  MultiSelect,
  Paper,
  NumberInput,
  SegmentedControl,
  Select,
  Slider,
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
import { resolveCategoricalPalette, stableColorMap, type StableColorMap } from '../../colors';
import { filtersExcludingOwn } from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';
import { ladderise, parseNewick, type PhyloNode, type PhyloTree, toNewick } from './phylo/newick';
import { computeLayout, descendants, type Layout } from './phylo/layout';
import { pruneToTips } from './phylo/prune';
import { cladeExtent, collapseNodes } from './phylo/collapse';
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

// Muted publication-friendly palette for categorical tip colouring, used
// when the deployment states no brand of its own.
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

/** Cap on numeric branch-length labels. Labelling every branch is what made
 *  the toggle unusable: on anything past a few dozen tips the numbers overlap
 *  into a grey band, and each one used to be a `layout.annotations` entry that
 *  Plotly re-positioned on every zoom notch. The longest branches are also the
 *  informative ones, so ranking by length and stopping keeps the signal. */
const BRANCH_LABEL_MAX = 20;

/** Past this many annotated nodes the support figures stop being placeable —
 *  they overlap each other and their own branches. The dots stay. */
const SUPPORT_LABEL_MAX = 60;

/** Undo depth. Deep enough to walk back through an exploration, bounded so a
 *  long session doesn't accumulate state nobody will use. */
const HISTORY_MAX = 50;
/** Changes closer together than this are one move. See the push effect. */
const COALESCE_MS = 350;

/** The four things that make up a view, for undo/redo. */
interface ViewState {
  highlightedRootId: number | null;
  collapsedIds: number[];
  focusMode: boolean;
  filterValues: string[];
}

const viewKey = (v: ViewState): string =>
  JSON.stringify([v.highlightedRootId, v.collapsedIds, v.focusMode, v.filterValues]);

/** Round a raw span down to a 1/2/5 x 10^k step, so the scale bar reads as a
 *  number a human would have picked. */
function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  return (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
}

/** Branch lengths span orders of magnitude between trees (substitutions per
 *  site vs. time), so a fixed number of decimals either rounds everything to
 *  zero or pads noise. `toPrecision` then `Number` drops trailing zeros and
 *  the float artefacts `niceStep` can produce (0.30000000000000004). */
function formatBranchLength(len: number): string {
  if (!Number.isFinite(len)) return '—';
  if (len !== 0 && Math.abs(len) < 1e-3) return len.toExponential(1);
  return String(Number(len.toPrecision(3)));
}

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
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const config = (metadata.config || {}) as PhylogeneticConfig;
  const isDark = colorScheme === 'dark';

  // ---- Tier-2 (intra-viz) controls ----------------------------------------
  const [layout, setLayout] = useState<Layout>(config.default_layout ?? 'rectangular');
  const [doLadderise, setDoLadderise] = useState<boolean>(config.ladderize ?? true);
  // Which metadata column supplies the tip label. `null` means the Newick name
  // — an ASV hash on an amplicon tree, which is why `label_col` exists and why
  // it now actually reaches the labels instead of only being fetched.
  const [labelCol, setLabelCol] = useState<string | null>(config.label_col ?? null);
  // Tip text used to appear below a hardcoded 80 tips and vanish above it, with
  // no way to argue. The threshold is the default, not the rule.
  const [labelLimit, setLabelLimit] = useState<number>(80);
  const [alignLabels, setAlignLabels] = useState<boolean>(false);
  // Metadata colour bands drawn beside the tips. Replaces `show_metadata_strip`,
  // which was a switch wired to nothing: one band per chosen column, which is
  // how you read taxonomy off a tree too dense to label.
  const [stripCols, setStripCols] = useState<string[]>(() =>
    config.show_metadata_strip && config.color_col ? [config.color_col] : [],
  );
  // Clades folded into a wedge, by node id. See phylo/collapse.ts.
  const [collapsedIds, setCollapsedIds] = useState<Set<number>>(() => new Set());
  // A wrapped row of badges above the plot ate vertical space and read as a
  // second toolbar. A column beside the tree is where a phylogeny legend
  // belongs, and it scrolls instead of pushing the tree down.
  const [legendPos, setLegendPos] = useState<'right' | 'bottom' | 'hidden'>('right');
  const [showSupport, setShowSupport] = useState<boolean>(false);
  // Support values are most useful as a warning, so the control reads as "show
  // me the nodes I should not trust" — only values at or below the threshold
  // are drawn, and 100 shows every annotated node.
  const [supportMax, setSupportMax] = useState<number>(100);
  // A scale bar is what phylogenetics tools actually show (iTOL, FigTree):
  // two SVG elements whose cost doesn't grow with the tree, against one text
  // node per branch. Per-branch numbers stay available as a separate,
  // capped toggle — `show_branch_lengths` in a dashboard config still means
  // "I want to read lengths", so it seeds that one.
  const [showScaleBar, setShowScaleBar] = useState<boolean>(true);
  const [showBranchLabels, setShowBranchLabels] = useState<boolean>(
    config.show_branch_lengths ?? false,
  );
  // Focus prunes the tree to the tips still in scope instead of ghosting the
  // rest. Off by default: ghosting answers "where is my selection in the
  // tree", focus answers "what is in my selection" — both are wanted, and
  // silently swapping one for the other on the first filter would be a
  // surprise. See phylo/prune.ts.
  const [focusMode, setFocusMode] = useState<boolean>(false);
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
  // The live viewport, tracked here rather than left to Plotly.
  //
  // `uirevision` only protects axis ranges that Plotly recorded as a *GUI*
  // edit — its own drag and scroll handlers store one as they run. Wheel zoom
  // no longer goes through them (it is coalesced into a `Plotly.relayout`, see
  // the wheel effect), and a programmatic relayout stores nothing. So every
  // figure recompute — clicking another clade is one — re-applied the fitted
  // ranges and threw the zoom away.
  //
  // Keeping the ranges here makes the view ours to re-supply on each rebuild.
  // The stamp is what invalidates them: a saved viewport belongs to one layout
  // kind, one focus state and one reset epoch, and means nothing under another.
  const viewRef = useRef<{ stamp: string; x: number[]; y: number[] } | null>(null);
  const viewStampRef = useRef<string>('');
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
  // ---- Category colours --------------------------------------------------
  // One place decides what colour a category gets, because three used to and
  // they could disagree: the tips, the metadata strips and the legend each
  // built their own map from their own set of values. A value present in the
  // strip but absent from the tip column then landed on a different colour in
  // the legend than on the tree.
  //
  // The scale is always keyed on the *whole* universe of the column, so a
  // filter that removes a category doesn't renumber the ones that remain. For
  // the tip colour column that universe is the server's distinct-values
  // response when it has arrived; otherwise, and for every strip column, it is
  // the full tree's own values.
  const valueAt = React.useCallback(
    (taxon: string, col: string): string => {
      const v = tipMeta.get(taxon)?.[col];
      return v == null || v === '' ? '—' : String(v);
    },
    [tipMeta],
  );

  const scaleForColumn = useMemo(() => {
    const cache = new Map<string, StableColorMap>();
    return (col: string): StableColorMap => {
      const hit = cache.get(col);
      if (hit) return hit;
      const universe: string[] = [];
      for (const leaf of tree?.leaves ?? []) {
        const sv = valueAt(leaf.name ?? '', col);
        if (!universe.includes(sv)) universe.push(sv);
      }
      universe.sort();
      const built = stableColorMap(
        col === colorCol && colorUniverse ? colorUniverse : universe,
        palette,
        (config.category_palettes || {})[col] || null,
      );
      cache.set(col, built);
      return built;
    };
  }, [tree, valueAt, colorCol, colorUniverse, palette, config.category_palettes]);

  const tipColors = useMemo<{ colorByTip: Map<string, string> }>(() => {
    const colorByTip = new Map<string, string>();
    if (!tree) return { colorByTip };
    if (!colorCol || !meta) {
      for (const leaf of tree.leaves) colorByTip.set(leaf.name ?? '', palette[0]);
      return { colorByTip };
    }
    const scale = scaleForColumn(colorCol);
    for (const leaf of tree.leaves) {
      const name = leaf.name ?? '';
      colorByTip.set(name, scale.get(valueAt(name, colorCol)));
    }
    return { colorByTip };
  }, [tree, colorCol, meta, valueAt, scaleForColumn]);

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

  // ---- Focus mode: the tree actually drawn --------------------------------
  // Two things can narrow the tree, and focus honours both: sidebar/global
  // filters (via `tipsInScope`) and a clade the user clicked. With both live
  // the clade wins, intersected with the filters — it is the narrower, more
  // deliberate of the two.
  const focusTaxa = useMemo<Set<string> | null>(() => {
    if (!focusMode) return null;
    if (highlightedRootId != null && selectionTaxa.length > 0) {
      const sel = new Set(selectionTaxa);
      if (!tipsInScope) return sel;
      return new Set([...sel].filter((t) => tipsInScope.has(t)));
    }
    return tipsInScope;
  }, [focusMode, highlightedRootId, selectionTaxa, tipsInScope]);

  // `pruneToTips` returns null when there is nothing to prune (no match, or
  // everything matched), which is exactly the "draw the full tree" case.
  // Selection state deliberately stays keyed on the full `tree`: what the user
  // picked shouldn't change because of how it is being displayed.
  const focusedTree = useMemo<PhyloTree | null>(() => {
    if (!tree || !focusTaxa) return tree;
    return pruneToTips(tree, focusTaxa) ?? tree;
  }, [tree, focusTaxa]);
  const focusActive = focusedTree !== tree;

  // Collapsing runs after focusing so a wedge reports what is hidden *in the
  // view*, not in the tree it was cut from.
  const displayTree = useMemo<PhyloTree | null>(() => {
    if (!focusedTree) return null;
    return collapseNodes(focusedTree, collapsedIds) ?? focusedTree;
  }, [focusedTree, collapsedIds]);

  // ---- Plotly figure ------------------------------------------------------
  const figure = useMemo(() => {
    const drawn = displayTree;
    if (!drawn) return null;
    const result = computeLayout(drawn, layout);
    const traces: any[] = [];
    // Focused onto the clade itself: every edge on screen belongs to the
    // selection, so there is nothing to dim and the tree draws normally.
    const spotlight =
      highlightedIds.size > 0 && !drawn.leaves.every((l) => highlightedIds.has(l.id));

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
    visit(drawn.root);

    // Selection is marked by taking contrast away from everything else rather
    // than by adding a colour to the clade: a coloured branch competes with the
    // colour-by-metadata already on the tips, and a thin accent line is the
    // first thing to disappear when the tree gets dense. Contrast survives
    // both.
    //
    // Two levels of "not this", because two different things can mean it and
    // they have to stay tellable apart: a tip filtered out of scope is nearly
    // gone, a tip merely outside the current selection is still legible.
    const baseEdgeColour = isDark ? 'rgba(220,220,220,0.65)' : 'rgba(40,40,40,0.65)';
    const ghostEdgeColour = isDark ? 'rgba(180,180,180,0.18)' : 'rgba(60,60,60,0.15)';
    const dimEdgeColour = isDark ? 'rgba(200,200,200,0.3)' : 'rgba(50,50,50,0.26)';

    const ghostXs: (number | null)[] = [];
    const ghostYs: (number | null)[] = [];
    const edgeXs: (number | null)[] = [];
    const edgeYs: (number | null)[] = [];
    const dimXs: (number | null)[] = [];
    const dimYs: (number | null)[] = [];
    for (const e of result.edges) {
      const isGhost = !subtreeInScope.get(e.to.id);
      const isDim = spotlight && !highlightedIds.has(e.to.id);
      const tgtXs = isGhost ? ghostXs : isDim ? dimXs : edgeXs;
      const tgtYs = isGhost ? ghostYs : isDim ? dimYs : edgeYs;
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
    if (dimXs.length > 0) {
      traces.push({
        type: 'scattergl' as const,
        mode: 'lines' as const,
        x: dimXs,
        y: dimYs,
        hoverinfo: 'skip',
        line: { color: dimEdgeColour, width: 1.4 },
        showlegend: false,
      });
    }
    // Last, so the selection draws over everything it is being distinguished
    // from.
    traces.push({
      type: 'scattergl' as const,
      mode: 'lines' as const,
      x: edgeXs,
      y: edgeYs,
      hoverinfo: 'skip',
      line: { color: baseEdgeColour, width: spotlight ? 1.8 : 1.4 },
      showlegend: false,
    });

    // Branch-length labels — a text trace, not `layout.annotations`. Plotly
    // re-positions every annotation on every relayout and never clips them to
    // the viewport, so on a real tree the toggle cost a few hundred SVG text
    // nodes per zoom notch. A trace is clipped and drawn with the rest of the
    // data. Only the `BRANCH_LABEL_MAX` longest branches are labelled — see
    // the constant for why. Restricted to layouts where an edge has a
    // well-defined midpoint in screen space.
    const labelledLayout =
      layout === 'rectangular' || layout === 'diagonal' || layout === 'hierarchical';
    if (showBranchLabels && labelledLayout) {
      const ranked = result.edges
        .filter((e) => Number.isFinite(e.to.branchLength))
        .sort((a, b) => b.to.branchLength - a.to.branchLength)
        .slice(0, BRANCH_LABEL_MAX);
      const lblXs: number[] = [];
      const lblYs: number[] = [];
      const lblTexts: string[] = [];
      for (const e of ranked) {
        // Rectangular polyline: pts[0]=parent, pts[1]=elbow, pts[2]=child.
        // Use the segment between elbow and child for the label position.
        const pts = e.pts;
        const last = pts[pts.length - 1];
        const prev = pts[pts.length - 2] ?? pts[0];
        lblXs.push((prev[0] + last[0]) / 2);
        lblYs.push((prev[1] + last[1]) / 2);
        lblTexts.push(formatBranchLength(e.to.branchLength));
      }
      if (lblXs.length > 0) {
        traces.push({
          type: 'scatter' as const,
          mode: 'text' as const,
          x: lblXs,
          y: lblYs,
          text: lblTexts,
          textposition: 'top center',
          textfont: { size: 9, color: isDark ? '#ced4da' : '#495057' },
          hoverinfo: 'skip',
          showlegend: false,
        });
      }
    }

    // Scale bar — the standard way to read distances off a phylogeny, and the
    // reason per-branch numbers can default to off. Two elements whose cost is
    // independent of the tree size, anchored in data coordinates on the
    // distance axis so the bar stays truthful through zoom, and on `paper` on
    // the other so it keeps its place at the edge of the plot.
    const shapes: any[] = [];
    const scaleAnnotations: any[] = [];
    const distanceIsX = layout === 'rectangular' || layout === 'diagonal';
    const distanceIsY = layout === 'hierarchical';
    if (showScaleBar && (distanceIsX || distanceIsY)) {
      const span = distanceIsX
        ? result.bbox.maxX - result.bbox.minX
        : result.bbox.maxY - result.bbox.minY;
      const barLen = niceStep(span / 5);
      const barColour = isDark ? 'rgba(233,236,239,0.85)' : 'rgba(33,37,41,0.85)';
      if (barLen > 0) {
        const start = distanceIsX ? result.bbox.minX : result.bbox.minY;
        shapes.push(
          distanceIsX
            ? {
                type: 'line',
                xref: 'x',
                yref: 'paper',
                x0: start,
                x1: start + barLen,
                y0: 0.03,
                y1: 0.03,
                line: { color: barColour, width: 2 },
              }
            : {
                type: 'line',
                xref: 'paper',
                yref: 'y',
                x0: 0.02,
                x1: 0.02,
                y0: start,
                y1: start + barLen,
                line: { color: barColour, width: 2 },
              },
        );
        scaleAnnotations.push(
          distanceIsX
            ? {
                xref: 'x',
                yref: 'paper',
                x: start + barLen / 2,
                y: 0.035,
                yanchor: 'bottom',
                text: formatBranchLength(barLen),
                showarrow: false,
                font: { size: 10, color: barColour },
              }
            : {
                xref: 'paper',
                yref: 'y',
                x: 0.025,
                y: start + barLen / 2,
                xanchor: 'left',
                text: formatBranchLength(barLen),
                showarrow: false,
                font: { size: 10, color: barColour },
              },
        );
      }
    }

    // ---- Right-hand gutter -------------------------------------------------
    // Strips and aligned labels live to the right of the deepest tip, in data
    // coordinates so they pan and zoom with the tree. Everything is a fraction
    // of the tree's own width: branch lengths are substitutions per site on one
    // tree and millions of years on the next, so any absolute offset is wrong
    // on most trees. Only the layouts where x *is* distance can host them.
    const gutterOk = distanceIsX;
    const spanX = Math.max(result.bbox.maxX - result.bbox.minX, 1e-9);
    const activeStrips = gutterOk ? stripCols.filter((c) => metaCols.includes(c)) : [];
    const stripStep = spanX * 0.04;
    const stripStart = result.bbox.maxX + spanX * 0.04;
    const alignOn = alignLabels && gutterOk;
    const labelX = stripStart + activeStrips.length * stripStep + spanX * 0.02;

    // Tips.
    const tipXs: number[] = [];
    const tipYs: number[] = [];
    const tipLabels: string[] = [];
    const tipColours: string[] = [];
    const tipSizes: number[] = [];
    const tipBorders: string[] = [];
    const tipOpacities: number[] = [];
    const tipTextColours: string[] = [];
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

    // Wedges for the collapsed clades. `cladeExtent` is read off the focused
    // tree, so a wedge reports and spans what focusing actually left inside it;
    // it returns null for an id that no longer names an internal node, which is
    // how a stale collapse from before a filter change quietly stops applying.
    const wedgeXs: (number | null)[] = [];
    const wedgeYs: (number | null)[] = [];
    const collXs: number[] = [];
    const collYs: number[] = [];
    const collIds: number[] = [];
    const collLabels: string[] = [];

    const searchLc = search.trim().toLowerCase();
    for (const leaf of drawn.leaves) {
      const name = leaf.name ?? '';
      const ext =
        collapsedIds.has(leaf.id) && focusedTree ? cladeExtent(focusedTree, leaf.id) : null;
      if (ext) {
        const x0 = leaf.x!;
        const y0 = leaf.y!;
        const x1 = gutterOk ? x0 + ext.depth : x0 + spanX * 0.05;
        wedgeXs.push(x0, x1, x1, null);
        wedgeYs.push(y0, y0 - 0.45, y0 + 0.45, null);
        collXs.push(x1);
        collYs.push(y0);
        collIds.push(leaf.id);
        collLabels.push(`${name || 'clade'} (${ext.leafCount})`);
        continue;
      }
      const inScope = isInScope(name);
      tipXs.push(leaf.x!);
      tipYs.push(leaf.y!);
      // The label is the taxonomy when a column is chosen and has a value for
      // this tip; the Newick id is the fallback, never a blank.
      const labelled = labelCol ? tipMeta.get(name)?.[labelCol] : null;
      tipLabels.push(
        labelled == null || labelled === '' ? name : String(labelled),
      );
      tipIds.push(leaf.id);
      tipColours.push(tipColors.colorByTip.get(name) ?? palette[0]);
      const isHi = !spotlight || highlightedIds.has(leaf.id);
      const shown = tipLabels[tipLabels.length - 1];
      const isSearchMatch =
        searchLc.length > 0 &&
        (name.toLowerCase().includes(searchLc) || shown.toLowerCase().includes(searchLc));
      // Size and border stay out of it — the selection is carried by contrast
      // alone, so a selected tip looks like an ordinary tip and everything else
      // recedes. A search hit still gets its own marker: it answers a different
      // question and has to survive whatever the selection is doing.
      tipSizes.push(isSearchMatch ? 13 : inScope ? 8 : 5);
      tipBorders.push(
        isSearchMatch ? '#FAB005' : isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.4)',
      );
      tipOpacities.push(!inScope ? 0.2 : isHi ? 1 : spotlight ? 0.28 : 1);
      tipTextColours.push(
        !inScope || (spotlight && !isHi)
          ? isDark
            ? 'rgba(233,236,239,0.3)'
            : 'rgba(33,37,41,0.3)'
          : isDark
            ? '#e9ecef'
            : '#212529',
      );
      // customdata: [leaf.id, ...meta values for each hoverCol]. Falls back to
      // '—' so the hover line stays aligned even when a rank isn't resolved.
      const row = tipMeta.get(name) || {};
      const customRow: (number | string)[] = [leaf.id];
      for (const c of hoverCols) {
        const v = row[c];
        customRow.push(v == null || v === '' ? '—' : String(v));
      }
      // Branch length last so the metadata indices above keep their positions.
      // Hover is where lengths live now that the labels are capped — without
      // it there was no way to read one specific branch at all.
      customRow.push(formatBranchLength(leaf.branchLength));
      tipCustomdata.push(customRow);
    }

    // For dense trees the tip-label text becomes unreadable noise (ASV hash
    // ids overlap each other). Threshold matches the QIIME2 q2-emperor
    // default: tip text only when there are <= 80 tips. Hover still shows
    // the full name. Always-text on small trees; markers-only on big ones.
    // ...but the threshold is a control now, because whether 200 labels are
    // noise depends on how tall the panel is and what the labels say. When
    // labels are aligned they come from their own trace, so the tips trace
    // draws markers only.
    const labelsOn = drawn.leaves.length <= labelLimit;
    const tipTextMode = labelsOn && !alignOn ? 'markers+text' : 'markers';
    // scattergl renders 10x+ faster for large tip counts and keeps pan/zoom
    // responsive on 10k+ tip trees. Plain scatter is preferable for small
    // trees because it supports text-mode rendering and richer hover boxes
    // out of the box, but at scale the WebGL trade-off is the right call.
    const tipTraceType = drawn.leaves.length > 500 ? 'scattergl' : 'scatter';

    // Build a hover template that shows the taxon (text) followed by each
    // metadata rank on its own line. Index [0] is leaf.id (used by the click
    // handler); metadata starts at index [1]. When no metadata columns exist
    // the template falls back to just the tip name.
    const hoverLines = hoverCols.map(
      (col, i) => `<b>${col}</b>: %{customdata[${i + 1}]}`,
    );
    hoverLines.push(`<b>branch</b>: %{customdata[${hoverCols.length + 1}]}`);
    const hoverTpl = `<b>%{text}</b><br>${hoverLines.join('<br>')}<extra></extra>`;

    traces.push({
      type: tipTraceType,
      mode: tipTextMode,
      x: tipXs,
      y: tipYs,
      text: tipLabels,
      customdata: tipCustomdata,
      textposition: layout === 'rectangular' || layout === 'diagonal' ? 'middle right' : 'top center',
      textfont: { size: 10, color: tipTextColours },
      hovertemplate: hoverTpl,
      marker: {
        size: tipSizes,
        color: tipColours,
        line: { color: tipBorders, width: 1 },
        opacity: tipOpacities,
      },
      showlegend: false,
    });

    // ---- Aligned labels + leader lines -------------------------------------
    // A phylogram staircases its tips, so a column of names read down the right
    // edge is what makes a tip list legible. The leader line is what keeps a
    // name attached to its branch once it has been moved off it.
    if (alignOn && labelsOn && tipXs.length > 0) {
      const leadXs: (number | null)[] = [];
      const leadYs: (number | null)[] = [];
      for (let i = 0; i < tipXs.length; i++) {
        leadXs.push(tipXs[i], labelX, null);
        leadYs.push(tipYs[i], tipYs[i], null);
      }
      traces.push({
        type: 'scattergl' as const,
        mode: 'lines' as const,
        x: leadXs,
        y: leadYs,
        hoverinfo: 'skip',
        line: { color: isDark ? 'rgba(180,180,180,0.25)' : 'rgba(60,60,60,0.2)', width: 1, dash: 'dot' },
        showlegend: false,
      });
      traces.push({
        type: 'scatter' as const,
        mode: 'text' as const,
        x: tipXs.map(() => labelX),
        y: tipYs,
        text: tipLabels,
        textposition: 'middle right',
        textfont: { size: 10, color: tipTextColours },
        hoverinfo: 'skip',
        showlegend: false,
      });
    }

    // ---- Metadata strips ---------------------------------------------------
    // One column of squares per chosen metadata column. This is how a dense
    // tree stays readable: the taxonomy is beside the tips as colour, so it
    // survives the tip count at which labels have to switch off.
    activeStrips.forEach((col, i) => {
      const scale = scaleForColumn(col);
      const xs: number[] = [];
      const ys: number[] = [];
      const colours: string[] = [];
      const labels: string[] = [];
      const opacities: number[] = [];
      for (const leaf of drawn.leaves) {
        if (collIds.includes(leaf.id)) continue;
        const sv = valueAt(leaf.name ?? '', col);
        xs.push(stripStart + i * stripStep);
        ys.push(leaf.y!);
        colours.push(scale.get(sv) ?? palette[0]);
        labels.push(sv);
        opacities.push(
          !isInScope(leaf.name ?? '') ? 0.2 : spotlight && !highlightedIds.has(leaf.id) ? 0.28 : 1,
        );
      }
      traces.push({
        type: 'scatter' as const,
        mode: 'markers' as const,
        x: xs,
        y: ys,
        text: labels,
        marker: { symbol: 'square', size: 9, color: colours, opacity: opacities, line: { width: 0 } },
        hovertemplate: `<b>${col}</b>: %{text}<extra></extra>`,
        showlegend: false,
      });
    });

    // ---- Collapsed clades --------------------------------------------------
    if (wedgeXs.length > 0) {
      traces.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        x: wedgeXs,
        y: wedgeYs,
        fill: 'toself',
        fillcolor: isDark ? 'rgba(220,220,220,0.35)' : 'rgba(40,40,40,0.28)',
        line: { color: baseEdgeColour, width: 1 },
        hoverinfo: 'skip',
        showlegend: false,
      });
      traces.push({
        type: 'scatter' as const,
        mode: 'markers+text' as const,
        x: collXs,
        y: collYs,
        text: collLabels,
        textposition: 'middle right',
        textfont: { size: 10, color: isDark ? '#e9ecef' : '#212529' },
        customdata: collIds,
        hovertemplate: '<b>%{text}</b><br><i>click to expand</i><extra></extra>',
        marker: { size: 10, color: 'rgba(0,0,0,0)', line: { width: 0 } },
        showlegend: false,
      });
    }

    // ---- Support values ----------------------------------------------------
    // Internal-node labels in a Newick from a bootstrap or aLRT run are the
    // support figures. Reading them is normally about finding the weak nodes,
    // so the threshold hides everything above it rather than below.
    if (showSupport) {
      const supXs: number[] = [];
      const supYs: number[] = [];
      const supTexts: string[] = [];
      const supRaw: number[] = [];
      let observedMax = 0;
      for (const n of drawn.nodes) {
        if (n.children.length === 0 || !n.name) continue;
        const v = Number(n.name);
        if (!Number.isFinite(v)) continue;
        if (v > observedMax) observedMax = v;
        supXs.push(n.x!);
        supYs.push(n.y!);
        supTexts.push(n.name);
        supRaw.push(v);
      }
      // Support is written on a 0-1 scale by some inference tools and 0-100 by
      // others, and nothing in the file says which. Read it off the values.
      const scale100 = observedMax > 1;
      const asPct = (v: number) => (scale100 ? v : v * 100);
      const keep = supRaw.map((v) => asPct(v) <= supportMax);
      const kept = (arr: any[]) => arr.filter((_, i) => keep[i]);

      if (keep.some(Boolean)) {
        // A dot per node rather than a number: text is the thing that stops
        // being legible when the nodes get dense, and support is read as "which
        // parts of this topology should I not believe" long before anyone needs
        // the exact figure. The dot carries that at any node count; the number
        // comes back when there are few enough to place.
        const dotColour = (v: number): string => {
          const pct = asPct(v);
          if (pct < 50) return '#E03131';
          if (pct < 70) return '#F08C00';
          if (pct < 90) return '#F4B400';
          return isDark ? 'rgba(160,160,160,0.55)' : 'rgba(90,90,90,0.45)';
        };
        traces.push({
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: kept(supXs),
          y: kept(supYs),
          text: kept(supTexts),
          marker: {
            size: 6,
            color: kept(supRaw).map(dotColour),
            line: { color: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(255,255,255,0.8)', width: 0.5 },
          },
          hovertemplate: '<b>support</b>: %{text}<extra></extra>',
          showlegend: false,
        });
        if (kept(supXs).length <= SUPPORT_LABEL_MAX) {
          traces.push({
            type: 'scatter' as const,
            mode: 'text' as const,
            x: kept(supXs),
            y: kept(supYs),
            text: kept(supTexts),
            textposition: 'bottom right',
            textfont: { size: 9, color: isDark ? '#ffc9c9' : '#c92a2a' },
            hoverinfo: 'skip',
            showlegend: false,
          });
        }
      }
    }

    // Internal-node click targets — invisible markers so the user can
    // click an internal node to highlight its subtree.
    const internalXs: number[] = [];
    const internalYs: number[] = [];
    const internalCustom: (number | string)[][] = [];
    for (const n of drawn.nodes) {
      if (n.children.length === 0) continue;
      internalXs.push(n.x!);
      internalYs.push(n.y!);
      // [id, branch length] — `onPlotClick` reads index 0 and tolerates the
      // bare-number shape this trace used to carry.
      internalCustom.push([n.id, formatBranchLength(n.branchLength)]);
    }
    traces.push({
      // Follows the tips' renderer rather than pinning SVG: this trace has one
      // marker per internal node, so on a large tree it was quietly the most
      // expensive thing on screen — a DOM node per node, redrawn on every pan.
      type: tipTraceType,
      mode: 'markers',
      x: internalXs,
      y: internalYs,
      customdata: internalCustom,
      hovertemplate:
        '<b>branch</b>: %{customdata[1]}<br><i>click to highlight subtree</i><extra></extra>',
      marker: { size: 6, color: 'rgba(0,0,0,0)', line: { width: 0 } },
      showlegend: false,
    });

    // Categorical legend (renders separately below the controls — using
    // plotly's legend would cramp the tree). We compute it here and
    // surface as React below via `tipColors.categories`.

    // Equal aspect ratio for circular/radial. Rectangular/hierarchical/
    // diagonal benefit from auto-scaling so leaf labels don't squash.
    const square = layout === 'circular' || layout === 'radial';

    // Plotly draws text in pixels, so the room a label needs cannot come out of
    // the data range — it has to be margin. ~6.2px per character at size 10,
    // capped so one pathological label can't take half the panel.
    const drawnLabels = labelsOn ? tipLabels : [];
    const widest = drawnLabels.reduce((m, t) => Math.max(m, t.length), 0);
    const labelRoom = widest > 0 ? Math.min(240, widest * 6.2 + 14) : 0;
    const collapsedRoom = collLabels.reduce((m, t) => Math.max(m, t.length), 0) * 6.2;
    const rightMargin = Math.max(16, labelRoom, collapsedRoom > 0 ? collapsedRoom + 14 : 0);

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        // A fixed 200px right gutter is why the tree never looked centred: it
        // was reserved whether or not anything was drawn in it, so a tree with
        // labels off sat hard against the left edge with a third of the panel
        // blank. Reserve what the longest label actually needs, and nothing
        // when there are no labels to place.
        margin: { l: 16, r: rightMargin, t: 8, b: 16 },
        // Padding is a fraction of the tree's own width. A fixed `+0.5` is
        // most of the panel on a tree whose total depth is 0.3 substitutions
        // per site, and invisible on one measured in millions of years.
        xaxis: {
          visible: false,
          range: [
            result.bbox.minX - spanX * 0.02,
            (alignOn || activeStrips.length > 0 ? labelX : result.bbox.maxX) + spanX * 0.04,
          ],
        },
        yaxis: {
          visible: false,
          scaleanchor: square ? 'x' : undefined,
          range: [result.bbox.minY - 0.5, result.bbox.maxY + 0.5],
        },
        showlegend: false,
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
        annotations: scaleAnnotations,
        shapes,
      },
    };
  }, [
    displayTree,
    focusedTree,
    layout,
    isDark,
    tipColors,
    tipMeta,
    valueAt,
    scaleForColumn,
    metaCols,
    highlightedIds,
    search,
    showBranchLabels,
    showScaleBar,
    tipsInScope,
    labelCol,
    labelLimit,
    alignLabels,
    stripCols,
    showSupport,
    supportMax,
    collapsedIds,
    tree,
  ]);

  // A saved viewport is only meaningful for the tree it was taken on. Changing
  // the layout kind recomputes every coordinate, and focusing changes which
  // tree is drawn — a crop of the old one would be arbitrary on the new.
  const viewStamp = `${layout}:${focusActive}:${viewEpoch}`;
  useEffect(() => {
    viewStampRef.current = viewStamp;
  }, [viewStamp]);

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
    const saved = viewRef.current?.stamp === viewStamp ? viewRef.current : null;
    return {
      ...figure.layout,
      // Fresh axis objects AND range arrays each time: Plotly's pan handler
      // mutates `range` in place on the layout it is handed, and a mutated
      // range leaking back into the memoized figure both breaks "Reset view"
      // (it would re-apply the panned range) and desyncs uirevision's idea of
      // what the supplied range is (snapping the view on the next recompute).
      xaxis: {
        ...figure.layout.xaxis,
        range: saved ? [...saved.x] : [...figure.layout.xaxis.range],
      },
      yaxis: {
        ...figure.layout.yaxis,
        range: saved ? [...saved.y] : [...figure.layout.yaxis.range],
      },
      dragmode: zoomEnabled ? ('pan' as const) : (false as const),
      uirevision: `phylo:${layout}:${viewEpoch}`,
    };
  }, [figure, zoomEnabled, layout, viewEpoch, viewStamp]);

  // Scroll-zoom is opt-in via the toolbar toggle — always-on wheel capture
  // steals page scroll (see RarefactionRenderer for the rationale). The hover
  // modebar is hidden: the toolbar is the single control point.
  //
  // `scrollZoom` stays off even when zoom is enabled: Plotly's own wheel
  // handler relayouts once per wheel event, and a trackpad emits them far
  // faster than a tree with thousands of edges can redraw, so the gesture
  // ends up minutes behind the fingers. The effect below does the same zoom
  // coalesced into one relayout per animation frame instead.
  const plotConfig = useMemo(
    () => ({
      displaylogo: false,
      responsive: true,
      displayModeBar: false,
      scrollZoom: false,
      doubleClick: zoomEnabled ? ('reset' as const) : (false as const),
    }),
    [zoomEnabled],
  );

  // Unique div id so the toggle handler can read the live viewport off the
  // Plotly graph div (react-plotly exposes no ref to it).
  // Also used as a CSS selector for the cursor rules below, so anything that
  // isn't valid in an identifier has to go — a component index is free-form.
  /** Record what the user is currently looking at, stamped for this view. */
  const captureView = () => {
    const gd = document.getElementById(plotDivId) as any;
    const xr = gd?._fullLayout?.xaxis?.range;
    const yr = gd?._fullLayout?.yaxis?.range;
    if (!xr || !yr) return;
    viewRef.current = { stamp: viewStampRef.current, x: [...xr], y: [...yr] };
  };

  const safeIndex = String(metadata.index).replace(/[^A-Za-z0-9_-]/g, '-');
  const plotDivId = `phylo-plot-${safeIndex}`;
  const rootId = `phylo-root-${safeIndex}`;
  // The Settings content is rendered by the chrome, outside this component's
  // DOM — but the stylesheet is global, so an id is enough to reach it and give
  // the popover the same one-cursor-per-region treatment as the panel.
  const controlsId = `phylo-controls-${safeIndex}`;

  // The cursor rules have to cover the whole card, and the card is not ours:
  // the Settings icon, the action row and the drag handle all live in
  // `.depictio-component-chrome`, which is an *ancestor* of this renderer.
  // CSS cannot select upwards, so the class goes on at runtime and comes off
  // on unmount. Everything below the chrome is then one stylesheet's problem.
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const card = rootRef.current?.closest('.depictio-component-chrome') as HTMLElement | null;
    if (!card) return;
    card.classList.add('phylo-cursor-pin');
    return () => card.classList.remove('phylo-cursor-pin');
  }, []);

  // Wheel zoom in two stages, because a relayout is not a cheap thing to do
  // sixty times a second: Plotly re-lays out and repaints every trace, and on a
  // real tree that is tens of thousands of segments. Even coalesced to one per
  // animation frame it could not keep up with a trackpad.
  //
  // So the gesture itself never touches Plotly. Each notch updates a CSS
  // transform on the plot's own SVG layers — pure compositing, no layout, no
  // repaint — which is what makes the zoom track the fingers. When the wheel
  // goes quiet the accumulated transform is converted into axis ranges, applied
  // as a single relayout, and the transform is dropped in the same frame.
  //
  // The visible trade-off is that stroke widths and label sizes scale with the
  // view mid-gesture and snap back on commit. That is the usual bargain for
  // this technique and it only lasts as long as the fingers are moving.
  const plotReady = Boolean(figure);
  useEffect(() => {
    if (!zoomEnabled || !plotReady) return;
    const gd = document.getElementById(plotDivId) as any;
    if (!gd) return;

    // Scale and translation accumulated since the last commit, in pixels.
    let scale = 1;
    let tx = 0;
    let ty = 0;
    let idle = 0;
    let raf = 0;

    const layers = (): HTMLElement[] =>
      Array.from(gd.querySelectorAll('.main-svg, .gl-container')) as HTMLElement[];

    const paint = () => {
      raf = 0;
      const t = `translate(${tx}px, ${ty}px) scale(${scale})`;
      for (const el of layers()) {
        el.style.transformOrigin = '0 0';
        el.style.transform = t;
      }
    };

    const commit = () => {
      const fl = gd._fullLayout;
      const applied = scale;
      const [dx, dy] = [tx, ty];
      scale = 1;
      tx = 0;
      ty = 0;
      for (const el of layers()) {
        el.style.transform = '';
        el.style.transformOrigin = '';
      }
      if (applied === 1 || !fl?.xaxis?.range || !fl?.yaxis?.range) return;
      // Invert the transform: a point that the transform moved to pixel p was
      // at (p - d) / s before it, and that is the pixel Plotly still thinks it
      // is at. Converting the two viewport corners back through it gives the
      // ranges that reproduce what the user is already looking at.
      const xa = fl.xaxis;
      const ya = fl.yaxis;
      const x0 = xa.p2d((0 - dx) / applied - xa._offset);
      const x1 = xa.p2d((xa._length - dx) / applied - xa._offset);
      const y0 = ya.p2d((ya._length - dy) / applied - ya._offset);
      const y1 = ya.p2d((0 - dy) / applied - ya._offset);
      if (![x0, x1, y0, y1].every((v) => Number.isFinite(v))) return;
      Plotly.relayout(gd, { 'xaxis.range': [x0, x1], 'yaxis.range': [y0, y1] })
        .then(captureView)
        .catch(() => {
          /* the div can go away between the last notch and the commit */
        });
    };

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = gd.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      // Zoom about the cursor: the point under it must map to the same pixel
      // before and after, which fixes the translation given the new scale.
      const k = Math.pow(1.0015, -ev.deltaY);
      scale *= k;
      tx = px - (px - tx) * k;
      ty = py - (py - ty) * k;
      if (!raf) raf = requestAnimationFrame(paint);
      window.clearTimeout(idle);
      idle = window.setTimeout(commit, 140);
    };

    gd.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      gd.removeEventListener('wheel', onWheel);
      window.clearTimeout(idle);
      if (raf) cancelAnimationFrame(raf);
      for (const el of layers()) {
        el.style.transform = '';
        el.style.transformOrigin = '';
      }
    };
  }, [zoomEnabled, plotReady, plotDivId]);

  const toggleZoom = () => {
    // Flipping the config rebuilds the plot, which would otherwise snap back to
    // the fitted ranges; capturing first means the rebuild re-supplies the view
    // the user is on.
    captureView();
    setZoomEnabled(!zoomEnabled);
  };

  const collapseSelected = () => {
    if (highlightedRootId == null) return;
    setCollapsedIds((prev) => new Set(prev).add(highlightedRootId));
    // The clade is now a wedge; leaving it highlighted would paint a selection
    // the user can no longer see the extent of.
    setHighlightedRootId(null);
  };

  const expandAll = () => setCollapsedIds(new Set());

  // ---- View history ------------------------------------------------------
  // "Back to full tree" throws away everything at once, which is the wrong
  // granularity for how the tree is actually explored: select, collapse,
  // filter, collapse again, then want the state from two moves ago. This is a
  // plain undo/redo over the four things that make up a view — what is
  // selected, what is collapsed, whether focus is on, and what this tree has
  // filtered the dashboard to.
  const snapshot = (): ViewState => ({
    highlightedRootId,
    collapsedIds: [...collapsedIds].sort((a, b) => a - b),
    focusMode,
    filterValues: [...ownFilterValues].sort(),
  });

  const histRef = useRef<{ entries: ViewState[]; index: number }>({ entries: [], index: -1 });
  const [histVersion, setHistVersion] = useState(0);
  // Restoring re-enters this state through the same setters as a user action,
  // and the filter half of it round-trips through the parent, arriving a
  // render or two later. A boolean "ignore the next change" would miss that
  // second arrival and record the restore as a new move; matching on the target
  // state instead survives however many renders it takes to land.
  const pendingRestoreRef = useRef<string | null>(null);
  const lastPushAtRef = useRef(0);

  useEffect(() => {
    const cur = snapshot();
    const key = viewKey(cur);
    if (pendingRestoreRef.current !== null) {
      if (pendingRestoreRef.current === key) pendingRestoreRef.current = null;
      return;
    }
    const h = histRef.current;
    const at = h.entries[h.index];
    if (at && viewKey(at) === key) return;
    const now = performance.now();
    if (at && now - lastPushAtRef.current < COALESCE_MS) {
      // One user action can land in two renders (the highlight now, the filter
      // once the parent has merged it). Fold those into a single step, or every
      // undo would need pressing twice.
      h.entries[h.index] = cur;
    } else {
      h.entries = [...h.entries.slice(0, h.index + 1), cur].slice(-HISTORY_MAX);
      h.index = h.entries.length - 1;
    }
    lastPushAtRef.current = now;
    setHistVersion((v) => v + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightedRootId, collapsedIds, focusMode, ownFilterValues]);

  const applyView = (v: ViewState) => {
    pendingRestoreRef.current = viewKey(v);
    setHighlightedRootId(v.highlightedRootId);
    setCollapsedIds(new Set(v.collapsedIds));
    setFocusMode(v.focusMode);
    const now = [...ownFilterValues].sort();
    if (now.join('\u0000') !== v.filterValues.join('\u0000')) emitTreeFilter(v.filterValues);
  };

  const canStepBack = histRef.current.index > 0;
  const canStepForward = histRef.current.index < histRef.current.entries.length - 1;

  const stepBack = () => {
    const h = histRef.current;
    if (h.index <= 0) return;
    h.index -= 1;
    setHistVersion((v) => v + 1);
    applyView(h.entries[h.index]);
  };

  const stepForward = () => {
    const h = histRef.current;
    if (h.index >= h.entries.length - 1) return;
    h.index += 1;
    setHistVersion((v) => v + 1);
    applyView(h.entries[h.index]);
  };
  // `histVersion` exists only to re-render for the button states above.
  void histVersion;

  const resetView = () => {
    viewRef.current = null;
    setViewEpoch((e) => e + 1);
  };

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
    <Stack gap="xs" id={controlsId}>
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
          Tip labels
        </Text>
        <Select
          size="xs"
          label="Label by"
          value={labelCol}
          onChange={setLabelCol}
          data={colorOptions}
          placeholder="Tree id"
          clearable
        />
        <NumberInput
          size="xs"
          label="Hide labels above"
          value={labelLimit}
          onChange={(v) => setLabelLimit(typeof v === 'number' ? v : 80)}
          min={0}
          step={20}
        />
        <Switch
          size="xs"
          checked={alignLabels}
          onChange={(e) => setAlignLabels(e.currentTarget.checked)}
          label="Align labels"
        />
      </Stack>
      {colorOptions.length > 0 ? (
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Metadata strips
          </Text>
          <MultiSelect
            size="xs"
            value={stripCols}
            onChange={setStripCols}
            data={colorOptions}
            placeholder="none"
            clearable
          />
        </Stack>
      ) : null}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Legend
        </Text>
        <SegmentedControl
          size="xs"
          data={[
            { value: 'right', label: 'Right' },
            { value: 'bottom', label: 'Bottom' },
            { value: 'hidden', label: 'Off' },
          ]}
          value={legendPos}
          onChange={(v) => setLegendPos(v as 'right' | 'bottom' | 'hidden')}
          fullWidth
        />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Support values
        </Text>
        <Switch
          size="xs"
          checked={showSupport}
          onChange={(e) => setShowSupport(e.currentTarget.checked)}
          label="Show support"
        />
        {showSupport ? (
          <>
            <Text size="xs" c="dimmed">
              Show at or below {supportMax}
            </Text>
            <Slider
              size="xs"
              value={supportMax}
              onChange={setSupportMax}
              min={0}
              max={100}
              step={5}
            />
          </>
        ) : null}
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Distances
        </Text>
        <Switch
          size="xs"
          checked={showScaleBar}
          onChange={(e) => setShowScaleBar(e.currentTarget.checked)}
          label="Scale bar"
        />
        <Switch
          size="xs"
          checked={showBranchLabels}
          onChange={(e) => setShowBranchLabels(e.currentTarget.checked)}
          label={`Label ${BRANCH_LABEL_MAX} longest branches`}
        />
      </Stack>
    </Stack>
  );

  // ---- Always-visible toolbar (zoom/pan + subtree actions) ----------------
  // Rendered in the frame body: the `controls` stack above only reaches the
  // Settings popover, which is exactly why the old Clear/Export buttons went
  // unnoticed. Subtree actions appear only while a clade is selected.
  // ---- Always-visible control strip --------------------------------------
  // One row, two modes. At rest it is the view controls; with a clade selected
  // or a filter live it becomes a context bar for that selection, the way a
  // file manager's toolbar switches when something is picked. Swapping rather
  // than appending keeps the strip one line tall in both states, so the tree
  // never resizes underneath the pointer — and there is only ever one place to
  // look for what acts on the selection.
  //
  // Facts read as inline key/value pairs, not a queue of badges: a row of pills
  // gives every fact the same shouty weight and stops being scannable past two
  // of them.
  const kv = (label: string, value: string) => (
    <Text size="xs" key={label}>
      <Text span c="dimmed" mr={4}>
        {label}
      </Text>
      <Text span fw={500}>
        {value}
      </Text>
    </Text>
  );

  const selectionMode = highlightedRootId != null || filterActive;

  // ---- What the selection is ---------------------------------------------
  // A pile of numbers is not an explanation. This produces a sentence first —
  // what the clade is, in the terms someone would use out loud — and the
  // figures under it, each labelled with what it actually measures and carrying
  // a note saying how to read it.
  //
  // The trap this fixes: Newick stores a node's support value in the same slot
  // as its name, so a clade whose "name" is `0.822` has no name at all. Showing
  // that as `Clade 0.822` invented a label and repeated the support figure.
  const selectionSummary = useMemo<{
    headline: string;
    rows: { label: string; value: string; hint: string }[];
  } | null>(() => {
    if (!tree || highlightedRootId == null) return null;
    const root = tree.nodes.find((n) => n.id === highlightedRootId);
    if (!root) return null;
    const kids = descendants(root);
    const leaves = kids.filter((n) => n.children.length === 0);
    const internal = kids.length - leaves.length;
    const rows: { label: string; value: string; hint: string }[] = [];

    // A label that parses as a number is a support value, not a name.
    const support = root.name ? Number(root.name) : NaN;
    const named = root.name && !Number.isFinite(support) ? root.name : null;

    const cols = [colorCol, ...stripCols.filter((c) => c !== colorCol)]
      .filter((c): c is string => Boolean(c) && metaCols.includes(c as string))
      .slice(0, 3);

    const breakdown = (col: string): [string, number][] => {
      const counts = new Map<string, number>();
      for (const leaf of leaves) {
        const sv = valueAt(leaf.name ?? '', col);
        counts.set(sv, (counts.get(sv) ?? 0) + 1);
      }
      return [...counts.entries()].sort((a, b) => b[1] - a[1]);
    };

    // The headline names the clade the way a person would: by what its tips
    // have in common, falling back to the tree's own label.
    let what = named ? `\u201c${named}\u201d` : 'This clade';
    if (!named && cols.length > 0) {
      const ranked = breakdown(cols[0]);
      const [topValue, topCount] = ranked[0] ?? ['', 0];
      if (ranked.length === 1) what = `All ${cols[0]} ${topValue}`;
      else if (leaves.length > 0 && topCount / leaves.length >= 0.8)
        what = `Mostly ${cols[0]} ${topValue}`;
      else what = `${ranked.length} ${cols[0]} values`;
    }
    const headline = `${what} \u2014 ${leaves.length} tip${
      leaves.length === 1 ? '' : 's'
    } descending from one common ancestor.`;

    rows.push({
      label: 'Tips',
      value: String(leaves.length),
      hint: 'Leaves of the tree inside this clade. These are the values sent as a filter.',
    });
    if (internal > 0) {
      rows.push({
        label: 'Branch points',
        value: String(internal),
        hint: 'Internal nodes inside the clade \u2014 the points where it splits.',
      });
    }
    const ext = cladeExtent(tree, highlightedRootId);
    if (ext && ext.depth > 0) {
      rows.push({
        label: 'Max depth',
        value: formatBranchLength(ext.depth),
        hint: "Longest distance from this clade's ancestor to one of its tips, in whatever units the tree's branch lengths use.",
      });
    }
    if (Number.isFinite(support)) {
      rows.push({
        label: 'Root support',
        value: root.name as string,
        hint: 'Confidence that this grouping is real, as written by whatever inferred the tree. A low value means the grouping is not well established.',
      });
    }
    for (const col of cols) {
      const ranked = breakdown(col);
      const shown = ranked.slice(0, 3).map(([v, n]) => `${v} ${n}`);
      if (ranked.length > 3) shown.push(`+${ranked.length - 3} more`);
      rows.push({
        label: col,
        value: shown.join(' \u00b7 '),
        hint: `How the ${leaves.length} tips in this clade break down by ${col}, commonest first.`,
      });
    }
    return { headline, rows };
  }, [tree, highlightedRootId, colorCol, stripCols, metaCols, valueAt]);

  // ---- Selection box -----------------------------------------------------
  // A real container under the view controls, stacked: a small heading so the
  // box says what it is, the facts as aligned key/value rows, then the actions
  // on their own line. Reading down a column beats scanning a wide row, and it
  // keeps every action the same short distance from the facts it acts on.
  // Present only while there is a selection, so nothing shifts at rest.
  const kvRow = (label: string, value: string, hint?: string) => (
    <Group key={label} gap="xs" wrap="nowrap" align="baseline">
      <Tooltip label={hint} withArrow multiline w={260} disabled={!hint} openDelay={300}>
        <Text
          size="xs"
          c="dimmed"
          style={{
            width: 92,
            flexShrink: 0,
            textDecoration: hint ? 'underline dotted' : undefined,
            textUnderlineOffset: 3,
          }}
        >
          {label}
        </Text>
      </Tooltip>
      <Text size="xs" fw={500} style={{ minWidth: 0, wordBreak: 'break-word' }}>
        {value}
      </Text>
    </Group>
  );

  const selectionBox = selectionMode ? (
    <Paper
      withBorder
      radius="sm"
      px="sm"
      py="xs"
      mx="sm"
      mb={6}
      w="fit-content"
      maw="calc(100% - var(--mantine-spacing-sm) * 2)"
      bg="var(--mantine-color-default-hover)"
      data-testid="phylo-selection-box"
    >
      <Stack gap={6}>
        <Text size="xs" fw={600} tt="uppercase" c="dimmed">
          Selection
        </Text>
        <Stack gap={4} data-testid="phylo-selection-info">
          {selectionSummary ? (
            <Text size="xs" style={{ maxWidth: 340 }}>
              {selectionSummary.headline}
            </Text>
          ) : null}
          <Stack gap={2}>
            {selectionSummary
              ? selectionSummary.rows.map((r) => kvRow(r.label, r.value, r.hint))
              : kvRow(
                  'Filtered',
                  `${ownFilterValues.length} tips`,
                  'This tree is filtering the dashboard to these tips. The clade they came from is no longer identifiable on the tree.',
                )}
            {filterActive && highlightedRootId != null
              ? kvRow(
                  'Filter',
                  selectionMatchesFilter ? 'this clade' : 'another clade',
                  'Whether the filter currently applied to the dashboard is the one for this clade, or one emitted from an earlier selection.',
                )
              : null}
          </Stack>
        </Stack>
        <Group gap="xs" wrap="wrap">
          {canFilter && highlightedRootId != null ? (
            <Button
              size="compact-xs"
              color="pink"
              variant={selectionMatchesFilter ? 'filled' : 'light'}
              leftSection={
                <Icon
                  icon={selectionMatchesFilter ? 'mdi:filter-off' : 'mdi:filter'}
                  width={13}
                  height={13}
                />
              }
              data-testid="phylo-filter-subtree"
              onClick={() =>
                selectionMatchesFilter ? emitTreeFilter([]) : emitTreeFilter(selectionTaxa)
              }
            >
              {selectionMatchesFilter ? 'Filtered' : 'Filter'}
            </Button>
          ) : null}
          {/* The button above only offers the way back while the highlight still
              matches what was emitted. Move the highlight and it flips to
              "Filter", leaving an active filter with no visible undo. */}
          {filterActive && !selectionMatchesFilter ? (
            <Button
              size="compact-xs"
              variant="default"
              color="pink"
              leftSection={<Icon icon="mdi:filter-off" width={13} height={13} />}
              data-testid="phylo-clear-filter"
              onClick={() => emitTreeFilter([])}
            >
              Clear filter
            </Button>
          ) : null}
          {highlightedRootId != null ? (
            <>
              <Button
                size="compact-xs"
                variant="light"
                leftSection={<Icon icon="mdi:arrow-collapse-vertical" width={13} height={13} />}
                data-testid="phylo-collapse-subtree"
                onClick={collapseSelected}
              >
                Collapse
              </Button>
              <Button
                size="compact-xs"
                variant="default"
                leftSection={<Icon icon="mdi:tray-arrow-down" width={13} height={13} />}
                data-testid="phylo-export-newick"
                onClick={exportSelectedNewick}
              >
                .nwk
              </Button>
            </>
          ) : null}
        </Group>
        {/* Its own line: it is the way out of every state this box can be in,
            not one more thing to do to the selection, and it was getting lost
            at the end of the action row. Spelled out too — the bare X it
            replaced was not being found at all. */}
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<Icon icon="mdi:arrow-left" width={13} height={13} />}
            data-testid="phylo-clear-selection"
            onClick={clearSelection}
          >
            Back to full tree
          </Button>
        </Group>
      </Stack>
    </Paper>
  ) : null;

  // ---- View controls -----------------------------------------------------
  // Always the same three, always in the same place. The selection box above
  // carries what changes, so this strip never rearranges under the pointer.
  const toolbar = (
    <Paper
      withBorder
      radius="sm"
      px="sm"
      py={6}
      mx="sm"
      mb={6}
      w="fit-content"
      maw="calc(100% - var(--mantine-spacing-sm) * 2)"
      bg="var(--mantine-color-default-hover)"
      className="phylo-controls-row"
      data-testid="phylo-toolbar"
    >
      <Group gap="md" wrap="nowrap">
        {/* Step through the view states one move at a time. Distinct from
            "Back to full tree", which discards every move at once. */}
        <Group gap={4} wrap="nowrap">
          <Tooltip label="Step back" withArrow>
            <ActionIcon
              size="sm"
              variant="default"
              aria-label="Step back"
              data-testid="phylo-step-back"
              disabled={!canStepBack}
              onClick={stepBack}
            >
              <Icon icon="mdi:undo" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Step forward" withArrow>
            <ActionIcon
              size="sm"
              variant="default"
              aria-label="Step forward"
              data-testid="phylo-step-forward"
              disabled={!canStepForward}
              onClick={stepForward}
            >
              <Icon icon="mdi:redo" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <Tooltip
          label={zoomEnabled ? 'Zoom on — scroll to zoom, drag to pan' : 'Enable zoom & pan'}
          withArrow
        >
          <ActionIcon
            size="sm"
            variant={zoomEnabled ? 'outline' : 'default'}
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
        <Tooltip
          label={
            focusMode
              ? 'Focus on — showing only the tips in scope'
              : 'Focus: prune the tree to the tips in scope'
          }
          withArrow
        >
          <ActionIcon
            size="sm"
            variant={focusMode ? 'outline' : 'default'}
            aria-pressed={focusMode}
            aria-label="Toggle focus mode"
            data-testid="phylo-focus-toggle"
            onClick={() => setFocusMode((f) => !f)}
          >
            <Icon icon="mdi:filter-variant" width={14} height={14} />
          </ActionIcon>
        </Tooltip>
        <Group gap="md" wrap="nowrap" style={{ minWidth: 0, overflow: 'hidden' }}>
          {focusActive
            ? kv('Focus', `${focusedTree?.leaves.length ?? 0} of ${tree?.leaves.length ?? 0} tips`)
            : null}
          {collapsedIds.size > 0 ? kv('Collapsed', `${collapsedIds.size}`) : null}
        </Group>
        {collapsedIds.size > 0 ? (
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<Icon icon="mdi:arrow-expand-vertical" width={13} height={13} />}
            data-testid="phylo-expand-all"
            onClick={expandAll}
          >
            Expand all
          </Button>
        ) : null}
      </Group>
    </Paper>
  );

  // ---- Legend ------------------------------------------------------------
  // Follows what is actually drawn, which is the whole point of a legend and
  // was not true before: entries came from the full tree, so focusing or
  // collapsing left categories listed that were no longer on screen, and the
  // metadata strips had no entries at all despite painting colour next to
  // every tip. One section per coloured column — the tip colour first, then
  // each strip — listing only the values present in the drawn tree. Colours
  // come from the shared scale, so they stay put when the list shortens.
  const legendGroups = useMemo(() => {
    if (!displayTree) return [] as { col: string; items: { value: string; color: string }[] }[];
    const cols = [colorCol, ...stripCols.filter((c) => c !== colorCol)].filter(
      (c): c is string => Boolean(c) && metaCols.includes(c as string),
    );
    return cols
      .map((col) => {
        const scale = scaleForColumn(col);
        const present: string[] = [];
        for (const leaf of displayTree.leaves) {
          if (collapsedIds.has(leaf.id)) continue;
          const sv = valueAt(leaf.name ?? '', col);
          if (!present.includes(sv)) present.push(sv);
        }
        present.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
        return {
          col,
          items: present.map((value) => ({ value, color: scale.get(value) })),
        };
      })
      .filter((g) => g.items.length > 0);
  }, [displayTree, collapsedIds, colorCol, stripCols, metaCols, valueAt, scaleForColumn]);

  const vertical = legendPos === 'right';
  const legendSwatches =
    legendGroups.length > 0 ? (
      <Stack gap={vertical ? 8 : 4} px="sm" pb={4}>
        {legendGroups.map((group) => (
          <Stack gap={2} key={group.col}>
            {/* Named only when there is more than one section — a single
                section's heading just repeats the "Colour by" control. */}
            {legendGroups.length > 1 ? (
              <Text size="10px" fw={600} tt="uppercase" c="dimmed">
                {group.col}
              </Text>
            ) : null}
            <Group gap={vertical ? 2 : 6} wrap="wrap" style={vertical ? { flexDirection: 'column', alignItems: 'flex-start' } : undefined}>
              {group.items.map((item) => (
                <Group gap={4} key={item.value} wrap="nowrap">
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      flexShrink: 0,
                      background: item.color,
                    }}
                  />
                  <span style={{ fontSize: 11 }}>{item.value}</span>
                </Group>
              ))}
            </Group>
          </Stack>
        ))}
      </Stack>
    ) : null;

  // Themed copies, memoised. `applyDataTheme`/`applyLayoutTheme` map to fresh
  // objects, so calling them inline in the JSX handed react-plotly a new
  // `data` array identity on every render — which is a full `Plotly.react`
  // diff, and also broke the WebGL-budget memo in AdvancedVizPlot that keys on
  // that identity. On a tree that is a whole-figure redraw for a hover.
  const themedData = useMemo(
    () => (figure ? applyDataTheme(figure.data, isDark, theme) : null),
    [figure, isDark, theme],
  );
  const themedLayout = useMemo(
    () => (plotLayout ? applyLayoutTheme(plotLayout as any, isDark, theme) : null),
    [plotLayout, isDark, theme],
  );

  // ---- Plotly click handler — toggle subtree highlight on click.
  const onPlotClick = (event: any) => {
    const cd = event?.points?.[0]?.customdata;
    if (cd == null) return;
    // customdata is now an array [leaf.id, ...metadata]. The leaf id lives
    // at index 0; older internal-node traces still pass a bare number, so
    // accept either shape.
    const id = Array.isArray(cd) ? cd[0] : cd;
    if (id == null) return;
    // A wedge is the only thing whose click means "undo", not "select".
    if (collapsedIds.has(id as number)) {
      setCollapsedIds((prev) => {
        const next = new Set(prev);
        next.delete(id as number);
        return next;
      });
      return;
    }
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
      <div
        id={rootId}
        ref={rootRef}
        style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}
      >
        {/* Plotly hands the cursor around as the pointer crosses its layers:
            an I-beam over any SVG text, a pointer over a hoverable marker, the
            four-way move cursor over the drag layer. Across a tree that is a
            different cursor every few pixels. Pin one for the whole plot — the
            drag affordance is what matters, and it is a property of the mode,
            not of whatever happens to be under the pointer. */}
        <style>{`
          /* One cursor per region, and the regions are big. Ordered by
             specificity, so the later, more specific rules win: card < control
             strips < plot. The popover is matched by id because it is
             portalled out of the card entirely. */
          .phylo-cursor-pin, .phylo-cursor-pin *,
          #${controlsId}, #${controlsId} * { cursor: default !important; }
          .phylo-cursor-pin .phylo-controls-row, .phylo-cursor-pin .phylo-controls-row *,
          .phylo-cursor-pin .depictio-component-actions,
          .phylo-cursor-pin .depictio-component-actions *,
          #${controlsId} input, #${controlsId} button,
          #${controlsId} [role="slider"], #${controlsId} [role="option"],
          #${controlsId} [role="checkbox"], #${controlsId} [role="radio"],
          #${controlsId} label { cursor: pointer !important; }
          .phylo-cursor-pin .depictio-drag-handle,
          .phylo-cursor-pin .depictio-drag-handle * { cursor: grab !important; }
          #${plotDivId}, #${plotDivId} * { cursor: ${zoomEnabled ? 'grab' : 'default'} !important; }
          #${plotDivId}:active, #${plotDivId}:active * { cursor: ${zoomEnabled ? 'grabbing' : 'default'} !important; }
          .phylo-cursor-pin text { user-select: none; }
        `}</style>
        {/* `flexShrink: 0` is load-bearing. Plotly asks for more height than the
            panel usually has, and a flex column shrinks every item to make it
            fit — including these rows, whose boxes then end up shorter than the
            controls drawn inside them. The visible bottom half of a button
            stops receiving clicks, which reads as a broken button rather than
            as a layout problem. */}
        <div style={{ flexShrink: 0 }}>{toolbar}</div>
        {selectionBox ? <div style={{ flexShrink: 0 }}>{selectionBox}</div> : null}
        {legendPos === 'bottom' ? <div style={{ flexShrink: 0 }}>{legendSwatches}</div> : null}
        <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'row' }}>
          <div style={{ flex: '1 1 auto', minWidth: 0 }}>
            {themedData && themedLayout ? (
              <AdvancedVizPlot
                divId={plotDivId}
                data={themedData as any}
                layout={themedLayout as any}
                onClick={onPlotClick}
                onRelayout={captureView}
                useResizeHandler
                style={{ width: '100%', height: '100%' }}
                config={plotConfig as any}
              />
            ) : null}
          </div>
          {legendPos === 'right' && legendSwatches ? (
            <div
              style={{
                flexShrink: 0,
                maxWidth: 150,
                overflowY: 'auto',
                overflowX: 'hidden',
                paddingTop: 4,
              }}
            >
              {legendSwatches}
            </div>
          ) : null}
        </div>
      </div>
    </AdvancedVizFrame>
  );
};

export default PhylogeneticRenderer;

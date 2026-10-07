import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Group,
  lighten,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import {
  fetchAdvancedVizData,
  fetchPhylogenyNewick,
  fetchUniqueValues,
  type InteractiveFilter,
  type StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import { sortCategoryValues } from '../../categoryColors';
import { filtersExcludingOwn } from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import PhyloViewSwitch from './PhyloViewSwitch';
import { usePersistedVizControl } from './usePersistedVizControl';
import type { PhylogeneticConfig } from './phylo/config';
import type { PhyloView } from './phylo/view';
import { parseNewick, type PhyloTree } from './phylo/newick';
import { PHYLO_PALETTE } from './phylo/palette';
import { pruneToTips } from './phylo/prune';
import {
  aggregateAbundance,
  cladogram,
  formatShare,
  rankValue,
  summariseByRank,
  type AbundanceSummary,
  type RankGroup,
} from './phylo/rankSummary';

/**
 * The phylogeny collapsed to one tip per lineage, for a landing tile.
 *
 * What a landing page wants from a tree of thousands of ASVs is not the tree:
 * it is which lineages make up the community and how they are related. This
 * draws the top `top_n` values of `collapse_rank` (Phylum, say) as the tips of
 * a cladogram whose topology comes from the real tree (see
 * phylo/rankSummary.ts for how a lineage is placed), each with a dot sized by
 * its share, coloured by `color_col` like the full tree's tips, and, when an
 * abundance table is bound, a strip of dots giving the same share within each
 * value of `abundance_split_col` (a site). The strip's dots keep the row's
 * colour (colour says which lineage, size says how much) unless the split
 * column has a palette in `category_palettes`: then each column wears its
 * site's colour, the colour that site has on every other tile, and the
 * lineage's colour stays on its branch, its own dot and its name.
 *
 * Filters reach it the way they reach the full tree: the tip metadata is
 * fetched with the dashboard's filters and the tree is pruned to the tips that
 * survive, so a Kingdom or Phylum filter redraws the summary over what is left;
 * the abundance table is fetched with the same filters, so a sample filter
 * changes the shares.
 *
 * Drawn as plain SVG rather than Plotly: it is a dozen rows whose geometry has
 * to line up to the pixel (branch, dot, name, share, strip), which is layout,
 * not plotting, and it has no use for zoom or pan.
 *
 * It is one of two views of the same component. The rank, and so whether this
 * view is drawn at all, is the router's (PhylogeneticRenderer, via
 * phylo/view.ts); its settings carry the switch back to the full tree.
 */

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PhylogeneticConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** The view switch, owned by the router; `view.rank` is the rank drawn. */
  view: PhyloView;
}

type SizeBy = 'tips' | 'abundance';

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Rough width of a label at `size` px, for fitting text without measuring. */
const textWidth = (text: string, size: number) => text.length * size * 0.56;

/** A strip header's width: 10.5 px, semibold, so a little wider than body text. */
const headerWidth = (text: string) => textWidth(text, 10.5) * 1.1;

function truncate(text: string, maxWidth: number, size: number): string {
  if (textWidth(text, size) <= maxWidth) return text;
  const fit = Math.max(1, Math.floor(maxWidth / (size * 0.56)) - 1);
  return `${text.slice(0, fit)}…`;
}

/**
 * The size of the element a callback ref is attached to. Mantine's
 * `useElementSize` observes the node its ref held at the last render, so a box
 * that mounts later (the frame renders no children while loading) is never
 * measured; a callback ref sees the node arrive.
 */
function useBoxSize(): [(node: HTMLDivElement | null) => void, { width: number; height: number }] {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;
    const read = () => {
      const r = node.getBoundingClientRect();
      setSize((s) =>
        Math.round(r.width) === s.width && Math.round(r.height) === s.height
          ? s
          : { width: Math.round(r.width), height: Math.round(r.height) },
      );
    };
    read();
    if (typeof ResizeObserver === 'undefined') return;
    observer.current = new ResizeObserver(read);
    observer.current.observe(node);
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, size];
}

const PhyloSummaryRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, view }) => {
  const config = (metadata.config || {}) as PhylogeneticConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const palette = resolveCategoricalPalette(theme, PHYLO_PALETTE);

  const taxonCol = config.taxon_col || 'taxon';
  const colorCol = config.color_col ?? null;
  const metaWf = config.metadata_wf_id ?? null;
  const metaDc = config.metadata_dc_id ?? null;
  const abundanceWf = config.abundance_wf_id ?? null;
  const abundanceDc = config.abundance_dc_id ?? null;
  const hasAbundance = Boolean(abundanceWf && abundanceDc);
  const valueCol = config.abundance_col || 'rel_abundance';
  const sampleCol = config.abundance_sample_col || 'sample';
  const splitCol = config.abundance_split_col ?? null;

  // ---- Tier-2 controls ------------------------------------------------------
  // The rank belongs to the router, which mounts this renderer only while one
  // is set (see PhylogeneticRenderer): changing it here can also mean leaving
  // for the full tree, which no renderer can do on its own behalf.
  const rank = view.rank ?? '';
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', 10);
  const [sizeBy, setSizeBy] = usePersistedVizControl<SizeBy>(metadata, 'size_by', 'tips');
  const useAbundance = sizeBy === 'abundance' && hasAbundance;

  // ---- Data ----------------------------------------------------------------
  const [newick, setNewick] = useState<string | null>(null);
  const [meta, setMeta] = useState<Record<string, unknown[]> | null>(null);
  const [abundanceRows, setAbundanceRows] = useState<Record<string, unknown[]> | null>(null);
  const [estimated, setEstimated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // A tree-selection filter emitted by this same component on another surface
  // (the full tree shares the index on its own tab) is not a scope for the
  // summary; drop it as the full tree drops its own.
  const fetchFilters = filtersExcludingOwn(filters, metadata.index, 'tree_selection');
  const filterKey = JSON.stringify(fetchFilters);

  useEffect(() => {
    if (!config.tree_dc_id) {
      setError('Phylogenetic: missing tree DC binding');
      setLoading(false);
      return;
    }
    if (!metaWf || !metaDc) {
      setError('Phylogeny summary: collapse_rank needs the tip metadata table (metadata_dc_id)');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const metaCols = Array.from(new Set([taxonCol, rank, ...(colorCol ? [colorCol] : [])]));
    const abundanceCols = Array.from(
      new Set([rank, valueCol, sampleCol, ...(splitCol ? [splitCol] : [])]),
    );
    Promise.all([
      fetchPhylogenyNewick(config.tree_dc_id),
      fetchAdvancedVizData({
        wfId: metaWf,
        dcId: metaDc,
        columns: metaCols,
        filters: fetchFilters,
        vizKind: 'phylogenetic',
      }),
      useAbundance
        ? fetchAdvancedVizData({
            wfId: abundanceWf as string,
            dcId: abundanceDc as string,
            columns: abundanceCols,
            filters: fetchFilters,
            vizKind: 'phylogenetic',
          })
        : Promise.resolve(null),
    ])
      .then(([nw, metaRes, abundanceRes]) => {
        if (cancelled) return;
        setNewick(nw);
        setMeta(metaRes.rows);
        setAbundanceRows(abundanceRes ? abundanceRes.rows : null);
        setEstimated(
          Boolean(metaRes.sampling?.degraded) || Boolean(abundanceRes?.sampling?.degraded),
        );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    config.tree_dc_id,
    metaWf,
    metaDc,
    taxonCol,
    rank,
    colorCol,
    useAbundance,
    abundanceWf,
    abundanceDc,
    valueCol,
    sampleCol,
    splitCol,
    filterKey,
    refreshTick,
  ]);

  // Whole universes, so a value keeps its colour (and a site its column) while
  // a filter takes others away — the full tree does the same for its tips.
  const [colourUniverse, setColourUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metaDc || !colorCol) {
      setColourUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metaDc, colorCol)
      .then((v) => !cancelled && setColourUniverse(v))
      .catch(() => {
        /* best-effort: falls back to the values in view */
      });
    return () => {
      cancelled = true;
    };
  }, [metaDc, colorCol]);

  const [splitUniverse, setSplitUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!useAbundance || !abundanceDc || !splitCol) {
      setSplitUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(abundanceDc, splitCol)
      .then((v) => !cancelled && setSplitUniverse(v))
      .catch(() => {
        /* best-effort: falls back to the values in view */
      });
    return () => {
      cancelled = true;
    };
  }, [useAbundance, abundanceDc, splitCol]);

  // ---- Summary ---------------------------------------------------------------
  const tree = useMemo<PhyloTree | null>(() => {
    if (!newick) return null;
    try {
      return parseNewick(newick);
    } catch {
      return null;
    }
  }, [newick]);

  const tipInfo = useMemo(() => {
    const group = new Map<string, string | null>();
    const colour = new Map<string, string | null>();
    if (!meta) return { group, colour };
    const taxa = (meta[taxonCol] ?? []) as unknown[];
    const ranks = (meta[rank] ?? []) as unknown[];
    const colours = colorCol ? ((meta[colorCol] ?? []) as unknown[]) : [];
    for (let i = 0; i < taxa.length; i++) {
      const t = String(taxa[i] ?? '');
      group.set(t, rankValue(ranks[i]));
      if (colorCol) colour.set(t, rankValue(colours[i]));
    }
    return { group, colour };
  }, [meta, taxonCol, rank, colorCol]);

  // The tips the filters leave. A tip missing from the filtered metadata is
  // out of scope, not unclassified: it is dropped from the tree before the
  // summary is taken, so it neither counts nor places a lineage.
  const scopedTree = useMemo<PhyloTree | null>(() => {
    if (!tree || !meta) return null;
    const inScope = tipInfo.group;
    let kept = 0;
    for (const leaf of tree.leaves) if (inScope.has(leaf.name ?? '')) kept++;
    if (kept === 0) return null;
    if (kept === tree.leaves.length) return tree;
    return pruneToTips(tree, new Set(inScope.keys())) ?? tree;
  }, [tree, meta, tipInfo]);

  const abundance = useMemo<AbundanceSummary | null>(() => {
    if (!useAbundance || !abundanceRows) return null;
    if (!(rank in abundanceRows)) return null;
    const agg = aggregateAbundance(abundanceRows, {
      rank,
      value: valueCol,
      sample: sampleCol in abundanceRows ? sampleCol : null,
      split: splitCol && splitCol in abundanceRows ? splitCol : null,
    });
    return agg.share.size > 0 ? agg : null;
  }, [useAbundance, abundanceRows, rank, valueCol, sampleCol, splitCol]);

  const { summary, sizedByReads } = useMemo(() => {
    if (!scopedTree) return { summary: null, sizedByReads: false };
    const groupOf = (tip: string) => tipInfo.group.get(tip) ?? null;
    const colourOf = (tip: string) => tipInfo.colour.get(tip) ?? null;
    const opts = {
      topN: clamp(Math.floor(topN || 10), 1, 60),
      colourOf,
      ladderize: config.ladderize ?? true,
    };
    const byReads = abundance ? summariseByRank(scopedTree, groupOf, { ...opts, abundance }) : null;
    if (byReads) return { summary: byReads, sizedByReads: true };
    // Abundance that matches none of the tree's lineages is a binding problem
    // (or a filter that left no reads), not a reason to draw nothing: the tips
    // still say what is there.
    return { summary: summariseByRank(scopedTree, groupOf, opts), sizedByReads: false };
  }, [scopedTree, tipInfo, topN, config.ladderize, abundance]);

  // ---- Colours ---------------------------------------------------------------
  const colourScale = useMemo(() => {
    const seen = colourUniverse ?? Array.from(new Set(tipInfo.colour.values())).filter(Boolean);
    return stableColorMap(
      seen as string[],
      palette,
      colorCol ? (config.category_palettes || {})[colorCol] || null : null,
    );
  }, [colourUniverse, tipInfo, palette, colorCol, config.category_palettes]);
  // The palette's darker hues (a navy, say) vanish as small dots on a dark
  // card; lift them a little there, legend included, so the tile stays legible.
  const tint = (c: string) => (isDark ? lighten(c, 0.22) : c);
  const colourFor = (g: RankGroup): string =>
    tint(colorCol && g.colourValue ? colourScale.get(g.colourValue) : palette[0]);

  // A palette for the split column (the cities, say) colours its columns.
  const splitPalette = splitCol ? (config.category_palettes || {})[splitCol] || null : null;
  const splitColour = (s: string, rowColour: string): string =>
    splitPalette?.[s] ? tint(splitPalette[s]) : rowColour;

  const splitValues = useMemo<string[]>(() => {
    if (!summary || !sizedByReads || !abundance || !abundance.split) return [];
    return sortCategoryValues([...(splitUniverse ?? []), ...abundance.splitValues]);
  }, [summary, sizedByReads, abundance, splitUniverse]);
  const splitInView = useMemo(() => new Set(abundance?.splitValues ?? []), [abundance]);
  // Reads asked for and bound, yet the summary had to be sized by tips: the
  // table names no value of this rank that the tree can place. Say so.
  const abundanceMissing = useAbundance && abundanceRows != null && !sizedByReads;

  // ---- Geometry --------------------------------------------------------------
  const [boxRef, { width, height }] = useBoxSize();
  const layout = useMemo(() => {
    if (!summary || width <= 0) return null;
    const rows = summary.shown.length;
    const strip = splitValues.length;
    const headerH = strip > 0 ? 20 : 2;
    const avail = Math.max(0, height - headerH - 4);
    const rowH = clamp(rows > 0 ? avail / rows : 24, 16, 30);
    const font = rowH >= 22 ? 12.5 : 11;
    const rMax = clamp(rowH * 0.42, 4, 11);
    const pad = 4;
    // Wide enough for the longest site name when the tile allows it.
    const headerW = Math.max(0, ...splitValues.map((v) => headerWidth(v) + 4));
    const cellW = strip > 0 ? clamp(Math.min(headerW, width * 0.11), 24, 72) : 0;
    const stripW = strip * cellW;
    const shareW = 40;
    const gap = strip > 0 ? 12 : 4;
    const shareRight = width - pad - stripW - gap;
    const fixed = 2 * rMax + 10 + shareW;
    const widest = Math.max(...summary.shown.map((g) => textWidth(g.group, font)));
    // The tree gets what the names leave it, within reason: wide enough to
    // read the branching, never so wide the names are cut first.
    const room = shareRight - pad - fixed;
    const treeW = clamp(Math.min(width * 0.32, room - widest), 36, 260);
    const depth = cladogram(summary.tree).depth;
    return {
      rows,
      headerH,
      rowH,
      font,
      rMax,
      treeX0: pad + 2,
      treeW,
      depth,
      leafX: pad + 2 + treeW,
      labelX: pad + 2 + treeW + 2 * rMax + 8,
      labelMax: Math.max(24, shareRight - shareW - (pad + 2 + treeW + 2 * rMax + 8)),
      shareRight,
      stripX0: width - pad - stripW,
      cellW,
      svgH: headerH + rows * rowH + 4,
    };
  }, [summary, width, height, splitValues]);

  const [hover, setHover] = useState<number | null>(null);

  // One scale for every dot, tip and strip alike, so a dot reads the same
  // wherever it is: area proportional to share.
  const maxShare = useMemo(() => {
    if (!summary) return 1;
    let m = 0;
    for (const g of summary.shown) {
      m = Math.max(m, g.share);
      if (g.splitShares) for (const v of Object.values(g.splitShares)) m = Math.max(m, v);
    }
    return m > 0 ? m : 1;
  }, [summary]);

  const measure = sizedByReads ? 'reads' : 'ASVs';
  const neutralEdge = isDark ? theme.colors.dark[2] : theme.colors.gray[5];
  const textColour = isDark ? theme.colors.dark[0] : theme.black;
  const dimColour = isDark ? theme.colors.dark[2] : theme.colors.gray[6];
  const trackColour = isDark ? theme.colors.dark[5] : theme.colors.gray[1];

  const svg = (() => {
    if (!summary || !layout) return null;
    const { points } = cladogram(summary.tree);
    const L = layout;
    const xOf = (level: number) =>
      L.depth > 0 ? L.treeX0 + (level / L.depth) * L.treeW : L.leafX;
    const yOf = (row: number) => L.headerH + (row + 0.5) * L.rowH;
    const radius = (share: number) =>
      share > 0 ? Math.max(2.2, L.rMax * Math.sqrt(share / maxShare)) : 0;

    // A clade whose tips all share a colour value is drawn in that colour, so
    // the kingdoms read as blocks; a mixed clade stays neutral.
    const leafColour = new Map<number, string>();
    summary.tree.leaves.forEach((leaf, i) => leafColour.set(leaf.id, colourFor(summary.shown[i])));
    const cladeColour = new Map<number, string | null>();
    const colourOfNode = (n: PhyloTree['root']): string | null => {
      if (n.children.length === 0) {
        const c = leafColour.get(n.id) ?? null;
        cladeColour.set(n.id, c);
        return c;
      }
      const cs = n.children.map(colourOfNode);
      const c = cs.every((x) => x != null && x === cs[0]) ? cs[0] : null;
      cladeColour.set(n.id, c);
      return c;
    };
    colourOfNode(summary.tree.root);

    const edges: React.ReactNode[] = [];
    for (const n of summary.tree.nodes) {
      if (!n.parent) continue;
      const p = points.get(n.parent.id)!;
      const c = points.get(n.id)!;
      const leafIdx = n.children.length === 0 ? summary.tree.leaves.indexOf(n) : -1;
      // A tip's branch runs on to its dot, so a small dot still sits on it.
      const xEnd = leafIdx >= 0 ? L.leafX + L.rMax + 3 : xOf(c.x);
      edges.push(
        <path
          key={`e${n.id}`}
          d={`M${xOf(p.x)},${yOf(p.y)} V${yOf(c.y)} H${xEnd}`}
          fill="none"
          stroke={cladeColour.get(n.id) ?? neutralEdge}
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={hover != null && leafIdx >= 0 && leafIdx !== hover ? 0.45 : 1}
        />,
      );
    }

    const rows = summary.shown.map((g, i) => {
      const y = yOf(i);
      const colour = colourFor(g);
      const label = truncate(g.group, L.labelMax, L.font);
      const tip = (
        <Stack gap={2}>
          <Text size="xs" fw={700}>
            {g.group}
            {g.colourValue ? (
              <Text span size="xs" c="dimmed" fw={400}>
                {' '}
                · {g.colourValue}
              </Text>
            ) : null}
          </Text>
          <Text size="xs">
            {sizedByReads
              ? `${formatShare(g.share)} of the reads (mean per sample)`
              : `${formatShare(g.share)} of the ASVs in view`}
          </Text>
          <Text size="xs" c="dimmed">
            {g.tips.toLocaleString()} ASV{g.tips === 1 ? '' : 's'} in the tree
            {g.coreTips < g.tips
              ? `; placed at its largest clean clade (${g.coreTips.toLocaleString()} of them)`
              : ', all in one clade'}
          </Text>
          {g.splitShares && splitValues.length > 0 ? (
            <Text size="xs">
              {splitValues
                .map((s) =>
                  splitInView.has(s) ? `${s} ${formatShare(g.splitShares![s] ?? 0)}` : `${s} –`,
                )
                .join(' · ')}
            </Text>
          ) : null}
        </Stack>
      );
      return (
        <Tooltip.Floating key={g.group} label={tip} multiline w={280} position="top">
          <g
            data-testid="phylo-summary-row"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          >
            <rect
              x={0}
              y={y - L.rowH / 2}
              width={width}
              height={L.rowH}
              rx={4}
              fill="transparent"
            />
            <circle
              cx={L.leafX + L.rMax + 3}
              cy={y}
              r={radius(g.share)}
              fill={colour}
              stroke={isDark ? theme.colors.dark[7] : theme.white}
              strokeWidth={1}
            />
            <text
              x={L.labelX}
              y={y}
              dominantBaseline="central"
              fontSize={L.font}
              fill={textColour}
              fontWeight={500}
            >
              {label}
            </text>
            <text
              x={L.shareRight}
              y={y}
              dominantBaseline="central"
              textAnchor="end"
              fontSize={L.font - 0.5}
              fill={dimColour}
              style={{ fontVariantNumeric: 'tabular-nums' }}
            >
              {formatShare(g.share)}
            </text>
            {splitValues.map((s, k) => {
              const cx = L.stripX0 + (k + 0.5) * L.cellW;
              const v = g.splitShares?.[s] ?? 0;
              return (
                <g key={s}>
                  <rect
                    x={cx - L.cellW / 2 + 2}
                    y={y - L.rowH / 2 + 2}
                    width={L.cellW - 4}
                    height={L.rowH - 4}
                    rx={3}
                    fill={trackColour}
                    opacity={0.7}
                  />
                  {splitInView.has(s) && v > 0 ? (
                    <circle
                      cx={cx}
                      cy={y}
                      r={Math.min(radius(v), L.cellW / 2 - 3)}
                      fill={splitColour(s, colour)}
                    />
                  ) : (
                    <text
                      x={cx}
                      y={y}
                      dominantBaseline="central"
                      textAnchor="middle"
                      fontSize={10}
                      fill={dimColour}
                    >
                      {splitInView.has(s) ? '·' : '–'}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </Tooltip.Floating>
      );
    });

    const headers = splitValues.map((s, k) => {
      const cx = L.stripX0 + (k + 0.5) * L.cellW;
      const label = headerWidth(s) <= L.cellW - 4 ? s : s.slice(0, 3);
      // The column's key: a dot of its colour before the name, where it fits.
      const key = splitPalette?.[s] && headerWidth(label) + 12 <= L.cellW - 4;
      const textX = key ? cx + 5 : cx;
      return (
        <g key={s}>
        {key ? (
          <circle
            cx={textX - headerWidth(label) / 2 - 7}
            cy={L.headerH - 10.5}
            r={3.5}
            fill={splitColour(s, neutralEdge)}
            opacity={splitInView.has(s) ? 1 : 0.4}
          />
        ) : null}
        <text
          x={textX}
          y={L.headerH - 7}
          textAnchor="middle"
          fontSize={10.5}
          fill={splitInView.has(s) ? dimColour : neutralEdge}
          fontWeight={600}
        >
          <title>{s}</title>
          {/* A name that does not fit is cut to three letters, an abbreviation
              rather than an ellipsis; the full name is in the tooltip. */}
          {label}
        </text>
        </g>
      );
    });

    return (
      <svg
        width={width}
        height={L.svgH}
        role="img"
        aria-label={`${metadata.title || 'Phylogeny'}: ${summary.shown.length} ${rank} lineages`}
        style={{ display: 'block', fontFamily: 'inherit', overflow: 'visible' }}
        data-testid="phylo-summary"
      >
        {headers}
        {/* The hovered row's band sits under the branches, so it cannot hide
            the one that leads to its own tip. */}
        {hover != null && hover < summary.shown.length ? (
          <rect
            x={0}
            y={yOf(hover) - L.rowH / 2}
            width={width}
            height={L.rowH}
            rx={4}
            fill="var(--mantine-color-default-hover)"
          />
        ) : null}
        {edges}
        {rows}
      </svg>
    );
  })();

  // ---- Legend ----------------------------------------------------------------
  const legendColours = useMemo(() => {
    if (!summary || !colorCol) return [] as { value: string; colour: string }[];
    const values = sortCategoryValues(summary.shown.map((g) => g.colourValue));
    return values.map((value) => ({
      value,
      colour: isDark ? lighten(colourScale.get(value), 0.22) : colourScale.get(value),
    }));
  }, [summary, colorCol, colourScale, isDark]);

  const hideLegend = Boolean(metadata.hide_legend);
  const legend =
    summary && !hideLegend ? (
      <Group gap={12} wrap="wrap" px={4} pt={6} style={{ rowGap: 2 }} data-testid="phylo-summary-legend">
        {legendColours.map((c) => (
          <Group gap={5} wrap="nowrap" key={c.value}>
            <span
              style={{ width: 9, height: 9, borderRadius: 9, background: c.colour, flexShrink: 0 }}
            />
            <Text size="xs">{c.value}</Text>
          </Group>
        ))}
        <Tooltip
          label={`Each tip is one ${rank}, placed where its largest clean clade sits in the ASV tree. Branch lengths are not to scale. Dot area is the ${
            sizedByReads ? 'mean share of a sample’s reads' : 'share of the ASVs in view'
          }.`}
          multiline
          w={280}
          withArrow
          openDelay={200}
        >
          <Text size="xs" c="dimmed" style={{ textDecoration: 'underline dotted', textUnderlineOffset: 3 }}>
            dot area: share of {measure}
          </Text>
        </Tooltip>
        {summary.other.groups > 0 ? (
          <Text size="xs" c="dimmed">
            not shown: {summary.other.groups.toLocaleString()} more, {formatShare(summary.other.share)} of{' '}
            {measure}
          </Text>
        ) : null}
        {abundanceMissing ? (
          <Text size="xs" c="orange">
            no {rank} in the abundance table: sized by ASVs
          </Text>
        ) : null}
      </Group>
    ) : null;

  // ---- Controls (Settings popover) --------------------------------------------
  // Every control is shown whether or not it can act, the way the switch above
  // them is: "Reads" with no abundance table bound is disabled and says what it
  // needs, rather than missing, which is how a user finds out the view exists.
  const controls = (
    <Stack gap="xs">
      <PhyloViewSwitch view={view} />
      <Select
        size="xs"
        label="Collapse to"
        value={rank}
        onChange={(v) => v && view.setRank(v)}
        data={view.choices}
        allowDeselect={false}
      />
      <NumberInput
        size="xs"
        label="Top N"
        description="Lineages drawn; the rest are counted under “not shown”"
        value={topN}
        onChange={(v) => typeof v === 'number' && setTopN(clamp(Math.floor(v), 1, 60))}
        min={1}
        max={60}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Size by
        </Text>
        <SegmentedControl
          size="xs"
          fullWidth
          value={hasAbundance ? sizeBy : 'tips'}
          onChange={(v) => setSizeBy(v as SizeBy)}
          data={[
            { value: 'abundance', label: 'Reads', disabled: !hasAbundance },
            { value: 'tips', label: 'ASVs' },
          ]}
        />
        {!hasAbundance ? (
          <Text size="xs" c="dimmed">
            Reads need an abundance table with a {rank} column (abundance_dc_tag).
          </Text>
        ) : null}
      </Stack>
    </Stack>
  );

  // ---- Show data ---------------------------------------------------------------
  const dataTable = useMemo(() => {
    if (!summary) return null;
    const cols = [rank, ...(colorCol ? [colorCol] : []), `share of ${measure}`, 'ASVs', 'ASVs in placed clade', ...splitValues];
    const rows: Record<string, unknown[]> = Object.fromEntries(cols.map((c) => [c, []]));
    for (const g of summary.shown) {
      rows[rank].push(g.group);
      if (colorCol) rows[colorCol].push(g.colourValue ?? '');
      rows[`share of ${measure}`].push(Number((g.share * 100).toFixed(2)));
      rows.ASVs.push(g.tips);
      rows['ASVs in placed clade'].push(g.coreTips);
      for (const s of splitValues) rows[s].push(Number(((g.splitShares?.[s] ?? 0) * 100).toFixed(2)));
    }
    return { rows, cols };
  }, [summary, rank, colorCol, measure, splitValues]);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Tree of life'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      estimated={estimated}
      emptyMessage={!loading && !error && !summary ? `No ${rank} in view` : undefined}
      dataRows={dataTable?.rows}
      dataColumns={dataTable?.cols}
    >
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <div ref={boxRef} style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}>
          {svg}
        </div>
        {legend ? <div style={{ flexShrink: 0 }}>{legend}</div> : null}
      </div>
    </AdvancedVizFrame>
  );
};

export default PhyloSummaryRenderer;

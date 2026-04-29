import React, { useEffect, useMemo, useRef } from 'react';
import { Group, Paper, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useMantineColorScheme } from '@mantine/core';
import CytoscapeComponent from 'react-cytoscapejs';
import type { Core, ElementDefinition } from 'cytoscape';

/** Shape of one row in the inputs to this component. Mirrors the slice of
 *  `data_collection` we read from the project response — `id`, `tag`, `type`
 *  plus the column list (used for table-typed DCs to render column nodes
 *  inside the DC background). */
export interface DataCollectionNode {
  id: string;
  tag: string;
  type: string;
  /** Best-effort column list; pulled from `dc.config.columns` /
   *  `dc.delta_table_schema` upstream. Truncated to 8 by the parent to
   *  match the Dash heuristic. */
  columns?: string[];
}

interface JoinEntry {
  /** Dash uses tag-keyed joins (`left_dc`, `right_dc`); we tolerate both
   *  the tag and the `dc1` / `dc_tag1` aliases. */
  left_dc?: string;
  right_dc?: string;
  dc1?: string;
  dc2?: string;
  dc_tag1?: string;
  dc_tag2?: string;
  on_columns?: string[];
  how?: string;
  name?: string;
}

interface LinkEntry {
  source_dc_id?: string;
  target_dc_id?: string;
  source_column?: string;
  target_type?: string;
  link_config?: {
    resolver?: string;
    target_field?: string;
  };
  enabled?: boolean;
  description?: string;
}

interface JoinsGraphProps {
  dataCollections: DataCollectionNode[];
  joins?: JoinEntry[];
  links?: LinkEntry[];
  /** Highlight the currently-selected DC's background node so the user sees
   *  its edges in context. Matches by DC id. */
  highlightDcId?: string;
}

const COLORS = {
  teal: '#15AABF',
  orange: '#FD7E14',
  blue: '#1C7ED6',
  grey: '#868E96',
};

/** Stylesheet — abridged port of the Dash get_depictio_cytoscape_stylesheet.
 *  Only the selectors we actually emit are defined; the rest of the long
 *  Dash stylesheet covers states (hover/select) we don't expose yet. */
// Loosened return type — the cytoscape `StylesheetCSS` typings (newly
// strict in cytoscape 3.33+) reject numeric values for `width`/`height`/
// `text-max-width` even though the runtime accepts them. Returning a
// permissive shape keeps the cast at the call site (line ~444) honest.
type LooseStyle = Record<string, unknown>;

function buildStylesheet(
  isDark: boolean,
  highlightId?: string,
): { selector: string; css: LooseStyle }[] {
  const text = isDark ? '#f8f9fa' : '#212529';
  const groupBg = isDark ? '#1e1e1e' : '#f8f9fa';
  const columnBg = isDark ? '#263238' : '#e3f2fd';

  return [
    // DC background (round-rectangle). The label sits above the box; the
    // column nodes are absolute-positioned inside.
    {
      selector: '.data-collection-background',
      css: {
        'background-color': groupBg,
        'border-color': COLORS.teal,
        'border-width': 2,
        label: 'data(label)',
        'text-valign': 'top',
        'text-halign': 'center',
        color: COLORS.teal,
        'font-size': 14,
        'font-weight': 700,
        shape: 'round-rectangle',
        width: 180,
        height: 'data(box_height)',
        'text-margin-y': -12,
        'text-wrap': 'wrap',
        'text-max-width': 160,
        opacity: 0.85,
        'text-opacity': 1,
      },
    },
    {
      selector: '.data-collection-background-multiqc',
      css: {
        'background-color': groupBg,
        'border-color': COLORS.orange,
        'border-width': 2,
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        color: COLORS.orange,
        'font-size': 13,
        'font-weight': 700,
        shape: 'round-rectangle',
        width: 140,
        height: 70,
        'text-wrap': 'wrap',
        'text-max-width': 120,
      },
    },
    {
      selector: '.data-collection-background-image',
      css: {
        'background-color': groupBg,
        'border-color': COLORS.teal,
        'border-width': 2,
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        color: COLORS.teal,
        'font-size': 13,
        'font-weight': 700,
        shape: 'round-rectangle',
        width: 140,
        height: 70,
      },
    },
    // Column nodes
    {
      selector: '.column-node',
      css: {
        'background-color': columnBg,
        'border-color': COLORS.blue,
        'border-width': 1,
        label: 'data(label)',
        color: text,
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': 10,
        width: 140,
        height: 32,
        shape: 'round-rectangle',
        'text-wrap': 'wrap',
        'text-max-width': 130,
      },
    },
    // Highlighted (join/link) columns get an orange tint
    {
      selector: '.join-column',
      css: {
        'border-width': 2,
        'border-color': COLORS.orange,
        'background-color': isDark ? '#3b2e16' : '#fff4e6',
        'font-weight': 700,
      },
    },
    // Join edges — solid teal
    {
      selector: '.join-edge',
      css: {
        'target-arrow-shape': 'triangle',
        'target-arrow-color': COLORS.teal,
        'line-color': COLORS.teal,
        width: 2.5,
        'curve-style': 'bezier',
        label: 'data(label)',
        'font-size': 9,
        color: text,
        'text-rotation': 'autorotate',
        'text-background-color': isDark ? '#1a1b1e' : '#ffffff',
        'text-background-opacity': 0.85,
        'text-background-padding': 2,
      },
    },
    // Link edges — dashed orange (runtime cross-DC filtering)
    {
      selector: '.link-edge',
      css: {
        'target-arrow-shape': 'triangle',
        'target-arrow-color': COLORS.orange,
        'line-color': COLORS.orange,
        'line-style': 'dashed',
        width: 2,
        'curve-style': 'bezier',
        label: 'data(label)',
        'font-size': 9,
        color: text,
        'text-rotation': 'autorotate',
        'text-background-color': isDark ? '#1a1b1e' : '#ffffff',
        'text-background-opacity': 0.85,
        'text-background-padding': 2,
      },
    },
    ...(highlightId
      ? [
          {
            selector: `node[id = "dc_bg_${highlightId}"]`,
            css: {
              'border-width': 4,
              'border-color': isDark ? '#fab005' : '#e67700',
              'background-color': isDark ? '#3b2e16' : '#fff8e1',
            },
          },
        ]
      : []),
  ];
}

/** Build cytoscape elements following the Dash original. For each DC:
 *  - emit a DC background round-rectangle
 *  - for table-typed DCs, emit one column node per column (max 8) inside the
 *    background
 *  Then for each join/link, emit an edge between the appropriate column
 *  nodes (or the DC background for multiqc/image link targets). */
function buildElements(
  dcs: DataCollectionNode[],
  joins: JoinEntry[],
  links: LinkEntry[],
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const dcByTag = new Map<string, DataCollectionNode>();
  const dcById = new Map<string, DataCollectionNode>();
  dcs.forEach((dc) => {
    dcByTag.set(dc.tag, dc);
    dcById.set(dc.id, dc);
  });

  // Hard-coded layout — Dash uses preset positions; we mirror the same
  // x_offset = i * 350 spacing.
  const X_STEP = 320;
  const COLUMN_SPACING = 42;

  dcs.forEach((dc, i) => {
    const dcType = (dc.type || 'table').toLowerCase();
    const x = i * X_STEP + 100;
    const isCompact = dcType === 'multiqc' || dcType === 'image';
    const cols = (dc.columns || []).slice(0, 8);

    const boxHeight = isCompact
      ? 70
      : Math.max(180, cols.length * COLUMN_SPACING + 60);
    const centerY = isCompact ? 140 : 140 + ((cols.length - 1) * COLUMN_SPACING) / 2;

    const bgClass = isCompact
      ? `data-collection-background-${dcType}`
      : 'data-collection-background';

    elements.push({
      data: {
        id: `dc_bg_${dc.id}`,
        label: `${dc.tag}\n[${dcType}]`,
        type: 'dc_background',
        dc_type: dcType,
        box_height: boxHeight,
      },
      position: { x, y: centerY },
      classes: bgClass,
    });

    // Column nodes for tables only
    if (dcType === 'table' && cols.length > 0) {
      cols.forEach((col, j) => {
        elements.push({
          data: {
            id: `${dc.tag}_${col}`,
            label: col,
            type: 'column',
            dc_tag: dc.tag,
            dc_id: dc.id,
          },
          position: { x, y: 140 + j * COLUMN_SPACING },
          classes: 'column-node',
        });
      });
    }
  });

  // Joins: solid teal edges between matching columns. Tag join columns so
  // the stylesheet can highlight them in orange.
  let edgeCounter = 0;
  (joins || []).forEach((j) => {
    const left = j.left_dc || j.dc_tag1 || j.dc1;
    const right = j.right_dc || j.dc_tag2 || j.dc2;
    const onCols = j.on_columns || [];
    if (!left || !right) return;
    const leftDc = dcByTag.get(left);
    const rightDc = dcByTag.get(right);
    if (!leftDc || !rightDc) return;

    onCols.forEach((col) => {
      [`${left}_${col}`, `${right}_${col}`].forEach((id) => {
        const node = elements.find((e) => e.data?.id === id);
        if (node) {
          const cls = (node.classes as string | undefined) ?? '';
          if (!cls.includes('join-column')) {
            node.classes = `${cls} join-column`.trim();
          }
        }
      });
    });

    if (onCols.length > 0) {
      const col = onCols[0];
      const sourceId = `${left}_${col}`;
      const targetId = `${right}_${col}`;
      // Sanity: only emit if both endpoints exist (table-typed DCs only).
      const haveSource = elements.some((e) => e.data?.id === sourceId);
      const haveTarget = elements.some((e) => e.data?.id === targetId);
      if (haveSource && haveTarget) {
        elements.push({
          data: {
            id: `join_edge_${edgeCounter}`,
            source: sourceId,
            target: targetId,
            label: (j.how || 'JOIN').toUpperCase(),
          },
          classes: 'join-edge',
        });
        edgeCounter += 1;
      }
    }
  });

  // Links: dashed orange edges from source column → target column (or DC
  // background for non-table targets).
  (links || []).forEach((l) => {
    if (l.enabled === false) return;
    const srcId = l.source_dc_id;
    const tgtId = l.target_dc_id;
    if (!srcId || !tgtId) return;
    const srcDc = dcById.get(srcId);
    const tgtDc = dcById.get(tgtId);
    if (!srcDc || !tgtDc) return;

    const sourceNodeId = `${srcDc.tag}_${l.source_column || ''}`;
    const haveSourceCol = elements.some((e) => e.data?.id === sourceNodeId);
    const sourceForEdge = haveSourceCol ? sourceNodeId : `dc_bg_${srcDc.id}`;

    const targetType = (l.target_type || 'table').toLowerCase();
    let targetForEdge: string;
    if (targetType === 'multiqc' || targetType === 'image') {
      targetForEdge = `dc_bg_${tgtDc.id}`;
    } else {
      const field = l.link_config?.target_field || l.source_column || '';
      const candidate = `${tgtDc.tag}_${field}`;
      targetForEdge = elements.some((e) => e.data?.id === candidate)
        ? candidate
        : `dc_bg_${tgtDc.id}`;
    }

    if (haveSourceCol) {
      const node = elements.find((e) => e.data?.id === sourceNodeId);
      if (node) {
        const cls = (node.classes as string | undefined) ?? '';
        if (!cls.includes('join-column')) {
          node.classes = `${cls} join-column`.trim();
        }
      }
    }

    elements.push({
      data: {
        id: `link_edge_${edgeCounter}`,
        source: sourceForEdge,
        target: targetForEdge,
        label: `Link (${l.link_config?.resolver || 'direct'})`,
      },
      classes: 'link-edge',
    });
    edgeCounter += 1;
  });

  return elements;
}

const JoinsGraph: React.FC<JoinsGraphProps> = ({
  dataCollections,
  joins,
  links,
  highlightDcId,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const cyRef = useRef<Core | null>(null);

  const elements = useMemo(
    () => buildElements(dataCollections, joins || [], links || []),
    [dataCollections, joins, links],
  );

  // Refit on element change so the preset layout stays centered when the
  // container width changes.
  useEffect(() => {
    if (!cyRef.current) return;
    cyRef.current.fit(undefined, 30);
  }, [elements]);

  if (dataCollections.length <= 1) return null;

  const edgeCount = elements.filter(
    (e) => e.data?.source && e.data?.target,
  ).length;

  // Box height grows with number of DCs (for advanced projects with 8 DCs the
  // preset layout needs a wider canvas to avoid clipping).
  const canvasHeight = Math.max(360, 220 + dataCollections.length * 12);

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Group gap="xs">
          <Icon
            icon="mdi:graph-outline"
            width={22}
            color="var(--mantine-color-grape-6)"
          />
          <Title order={5}>Data Collection Relationships</Title>
          <Text size="xs" c="dimmed">
            {edgeCount} {edgeCount === 1 ? 'edge' : 'edges'} ·{' '}
            {(joins || []).length} join
            {(joins || []).length === 1 ? '' : 's'} · {(links || []).length}{' '}
            link
            {(links || []).length === 1 ? '' : 's'}
          </Text>
        </Group>
        {edgeCount === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="md">
            No joins or links defined. Each data collection stands alone.
          </Text>
        ) : (
          <CytoscapeComponent
            elements={elements as ElementDefinition[]}
            style={{ width: '100%', height: canvasHeight }}
            stylesheet={buildStylesheet(isDark, highlightDcId) as never}
            layout={{ name: 'preset', padding: 30, fit: true }}
            cy={(cy: Core) => {
              cyRef.current = cy;
            }}
          />
        )}
      </Stack>
    </Paper>
  );
};

export default JoinsGraph;

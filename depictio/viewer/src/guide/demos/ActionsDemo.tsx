/**
 * The "component actions" demo: a tile of the kind picked, wearing the real
 * action row, and the list of everything a reader or an author can do to it.
 *
 * The row is not a picture of the row. It is `ComponentChrome` itself, around a
 * schematic body, on one of this tab's own components when it has one of that
 * kind — so the icons, colours, tooltips and popovers are the ones the tile on
 * the page has, metadata included. The few actions a renderer adds to the row
 * (viz settings, show data, the source-tab link) are drawn from the same style
 * table their buttons read (`TILE_ACTION_STYLE`), and the legend below reads it
 * too, so the two cannot disagree.
 *
 * The demo acts on itself only: its analysis switch and its "filtering" state
 * are local, the inspector and the group actions are stubbed.
 */
import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Group,
  Menu,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ComponentChrome,
  componentTypeVisual,
  editActionsFor,
  InspectorProvider,
  LoadAllButton,
  ownControlsFor,
  rowActionsFor,
  SaveGroupContext,
  SelectionHintAction,
  supportsSelectionGrouping,
  TILE_ACTION_STYLE,
  useGroupingColor,
  useGroupingColorVar,
  useInspectorControl,
} from 'depictio-react-core';
import type {
  GuideEditAction,
  GuideModel,
  GuideRowAction,
  GuideTileType,
  InspectorControl,
  SaveGroupApi,
  StoredMetadata,
  TileActionStyle,
} from 'depictio-react-core';

// ---------------------------------------------------------------------------
// The kinds of tile
// ---------------------------------------------------------------------------

/** Kinds always offered; the rest only where the tab has one. */
const ALWAYS: GuideTileType[] = ['figure', 'card', 'table', 'map', 'multiqc', 'advanced_viz', 'text'];

const SHORT_LABEL: Record<GuideTileType, string> = {
  figure: 'Figure',
  card: 'Card',
  table: 'Table',
  map: 'Map',
  multiqc: 'MultiQC',
  advanced_viz: 'Advanced',
  text: 'Text',
  image: 'Image',
  interactive: 'Filter',
};

/** What makes a stand-in of each kind one a selection can be made on. */
const SELECTABLE: Partial<Record<GuideTileType, Partial<StoredMetadata>>> = {
  figure: { visu_type: 'scatter', selection_enabled: true },
  table: { row_selection_enabled: true },
  map: { selection_enabled: true, map_type: 'scatter_map' },
  image: { image_column: 'image' },
  advanced_viz: {
    viz_kind: 'embedding',
    config: { selection_enabled: true, sample_id_col: 'sample' },
  },
};

const STAND_IN_TITLE: Record<GuideTileType, string> = {
  figure: 'Samples by depth',
  card: 'Samples',
  table: 'Sample sheet',
  map: 'Sampling stations',
  multiqc: 'Read quality',
  advanced_viz: 'Embedding',
  text: 'Notes',
  image: 'Images',
  interactive: 'Locality',
};

/** The tile the demo wears the row on: this tab's own of that kind, or a
 *  stand-in. Under an id of its own, so nothing keyed on component ids (the
 *  inspector, the grid's height fitting) takes it for the tile on the page. */
function demoTile(type: GuideTileType, components: readonly StoredMetadata[]): StoredMetadata {
  const own =
    components.find((m) => m.component_type === type && supportsSelectionGrouping(m, true)) ??
    components.find((m) => m.component_type === type);
  const base: StoredMetadata = own ?? ({
    index: type,
    component_type: type,
    title: STAND_IN_TITLE[type],
  } as StoredMetadata);
  return { ...base, index: `guide-demo:${base.index}` };
}

// ---------------------------------------------------------------------------
// Glyphs drawn as the app draws them
// ---------------------------------------------------------------------------

/** An action's icon in its real button: subtle, `sm`, a 16px glyph. */
const Glyph: React.FC<{
  style: TileActionStyle;
  color?: string;
  variant?: 'subtle' | 'filled';
  disabled?: boolean;
  label?: string;
  /** In a legend row the label is beside it: no tooltip, out of the tab order. */
  legend?: boolean;
}> = ({ style, color, variant = 'subtle', disabled, label, legend }) => {
  const icon = (
    <ActionIcon
      variant={variant}
      color={color ?? style.color}
      size="sm"
      disabled={disabled}
      aria-label={legend ? undefined : (label ?? style.label)}
      aria-hidden={legend || undefined}
      tabIndex={legend ? -1 : undefined}
      component={legend ? 'span' : 'button'}
      style={legend ? { cursor: 'default' } : undefined}
    >
      <Icon icon={style.icon} width={16} height={16} />
    </ActionIcon>
  );
  return legend ? (
    icon
  ) : (
    <Tooltip label={label ?? style.label} withArrow>
      {icon}
    </Tooltip>
  );
};

/** What a schematic tile body looks like, per kind. */
const Body: React.FC<{ type: GuideTileType; title: string }> = ({ type, title }) => {
  const bars = (heights: number[]) => (
    <Box className="depictio-guide-bars" pt={8} pb={8} style={{ height: '100%' }}>
      {heights.map((h, i) => (
        <span key={i} style={{ height: `${h}%` }} />
      ))}
    </Box>
  );
  const dots = (
    <Box className="depictio-guide-dots" style={{ position: 'relative', height: '100%' }}>
      {[
        [14, 62],
        [24, 40],
        [36, 56],
        [48, 30],
        [58, 46],
        [70, 22],
        [80, 38],
      ].map(([x, y], i) => (
        <span key={i} style={{ left: `${x}%`, top: `${y}%` }} />
      ))}
    </Box>
  );
  let inner: React.ReactNode;
  switch (type) {
    case 'card':
      inner = (
        <Stack gap={0} justify="center" h="100%">
          <Text size="xl" fw={700} c="var(--mantine-primary-color-filled)">
            85
          </Text>
          <Text size="xs" c="dimmed">
            (Count)
          </Text>
        </Stack>
      );
      break;
    case 'table':
      inner = (
        <Stack gap={4} pt={4}>
          {[0, 1, 2, 3].map((i) => (
            <Box key={i} className="depictio-guide-row" data-head={i === 0 || undefined} />
          ))}
        </Stack>
      );
      break;
    case 'text':
      inner = (
        <Stack gap={6} pt={6}>
          {[92, 84, 60].map((w, i) => (
            <Box key={i} className="depictio-guide-line" style={{ width: `${w}%` }} />
          ))}
        </Stack>
      );
      break;
    case 'image':
      inner = (
        <SimpleGrid cols={4} spacing={6} pt={4}>
          {[0, 1, 2, 3].map((i) => (
            <Box key={i} className="depictio-guide-thumb" />
          ))}
        </SimpleGrid>
      );
      break;
    case 'interactive':
      inner = <Box className="depictio-guide-input" mt={6} />;
      break;
    case 'map':
    case 'advanced_viz':
      inner = dots;
      break;
    case 'multiqc':
      inner = bars([30, 64, 52, 80, 44, 70]);
      break;
    default:
      inner = bars([46, 72, 58, 88, 64]);
  }
  return (
    <Box p="sm" h="100%" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <Text size="sm" fw={600} truncate pr={type === 'card' || type === 'interactive' ? 72 : 40}>
        {title}
      </Text>
      <Box style={{ flex: 1, minHeight: 0, position: 'relative' }}>{inner}</Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// The demo
// ---------------------------------------------------------------------------

const noop = () => undefined;

export const ActionsDemo: React.FC<{
  model: GuideModel;
  components: readonly StoredMetadata[];
  mode: 'view' | 'edit';
}> = ({ model, components, mode }) => {
  const present = new Map(model.tileTypes.map((t) => [t.type, t.count]));
  const types = useMemo(() => {
    const extra = (['image', 'interactive'] as GuideTileType[]).filter(
      (t) => present.has(t) || (t === 'interactive' && model.filters.total > 0),
    );
    return [...ALWAYS, ...extra];
    // `present` is derived from the model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model]);
  const [type, setType] = useState<GuideTileType>(model.tileTypes[0]?.type ?? 'figure');
  const [analysis, setAnalysis] = useState(false);
  const [filtering, setFiltering] = useState(false);
  const [editor, setEditor] = useState(mode === 'edit');

  const groupingColor = useGroupingColor();
  const groupingColorVar = useGroupingColorVar();
  // The inspect action shows only where the app has the inspector on; here it
  // selects nothing.
  const appInspector = useInspectorControl();
  const inspector = useMemo<InspectorControl | null>(
    () => (appInspector ? { selectedId: null, select: noop } : null),
    [appInspector],
  );

  const row = rowActionsFor(type);
  const selectable = row.some((a) => a.key === 'group');
  const hasReset = row.some((a) => a.key === 'reset');
  const tile = useMemo(() => {
    const t = demoTile(type, components);
    return analysis && selectable ? { ...t, ...SELECTABLE[type] } : t;
  }, [type, components, analysis, selectable]);
  const saveGroupApi = useMemo<SaveGroupApi>(
    () => ({ groups: [], createGroup: () => null, clearSelection: noop, analysisEngaged: analysis }),
    [analysis],
  );
  const edit = editActionsFor(type, {
    hasSections: (model.sections.foldable.length > 0 || model.sections.headings > 0),
    hasOtherTabs: model.tabs.count > 1,
  });
  const menuItems = edit.filter((a) => a.key !== 'drag' && a.key !== 'resize');

  // What the renderer adds after the chrome's own icons, in its order.
  const extras: React.ReactNode[] = [];
  if (analysis && selectable) extras.push(<SelectionHintAction key="hint" />);
  for (const a of row) {
    if (a.key === 'loadAll') {
      extras.push(
        <LoadAllButton
          key="load"
          state={{
            reduced: true,
            full: false,
            loading: false,
            toggle: noop,
            noun: type === 'table' ? 'rows' : 'points',
          }}
        />,
      );
    } else if (a.key === 'settings' || a.key === 'data') {
      extras.push(<Glyph key={a.key} style={a} />);
    }
  }
  if (editor) {
    extras.push(
      <Menu key="menu" position="bottom-end" shadow="md" width={220} withinPortal>
        <Menu.Target>
          <ActionIcon variant="subtle" size="sm" aria-label={TILE_ACTION_STYLE.menu.label}>
            <Icon icon={TILE_ACTION_STYLE.menu.icon} width={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          {menuItems.map((a) => (
            <React.Fragment key={a.key}>
              {a.key === 'delete' && <Menu.Divider />}
              <Menu.Item color={a.color} leftSection={<Icon icon={a.icon} width={14} />}>
                {a.label}
              </Menu.Item>
            </React.Fragment>
          ))}
        </Menu.Dropdown>
      </Menu>,
    );
  }

  const count = present.get(type) ?? 0;
  const visual = componentTypeVisual(type);
  const options = types.map((t) => ({ value: t, label: SHORT_LABEL[t] }));
  const tall = type !== 'card' && type !== 'interactive';

  return (
    <Stack gap="md" data-testid="guide-actions-demo">
      <Box>
        <SegmentedControl
          visibleFrom="sm"
          fullWidth
          size="xs"
          value={type}
          onChange={(v) => setType(v as GuideTileType)}
          data={options}
          aria-label="Kind of component"
        />
        <Select
          hiddenFrom="sm"
          size="sm"
          value={type}
          onChange={(v) => v && setType(v as GuideTileType)}
          data={options}
          allowDeselect={false}
          aria-label="Kind of component"
          leftSection={<Icon icon={visual.icon} width={16} />}
        />
      </Box>

      <Group gap="md" wrap="wrap" justify="space-between">
        <Group gap={6} wrap="nowrap">
          <Icon icon={visual.icon} width={16} style={{ color: visual.color }} />
          <Text size="sm" c="dimmed">
            {count > 0
              ? `${count} on this tab — the row below is one of theirs`
              : `None on this tab — a stand-in shows the row`}
          </Text>
        </Group>
        <Group gap="md" wrap="wrap">
          {selectable && (
            <Switch
              size="xs"
              label="Analysis on"
              checked={analysis}
              onChange={(e) => setAnalysis(e.currentTarget.checked)}
            />
          )}
          {hasReset && type !== 'interactive' && (
            <Switch
              size="xs"
              label="A selection filters"
              checked={filtering}
              onChange={(e) => setFiltering(e.currentTarget.checked)}
            />
          )}
          <Switch
            size="xs"
            label="In the editor"
            checked={editor}
            onChange={(e) => setEditor(e.currentTarget.checked)}
          />
        </Group>
      </Group>

      <InspectorProvider value={inspector}>
        <SaveGroupContext.Provider value={saveGroupApi}>
          <Box
            className="depictio-guide-demo-tile"
            h={tall ? 300 : 140}
            style={{ '--depictio-grouping-color': groupingColorVar } as React.CSSProperties}
            data-testid="guide-actions-tile"
          >
            <ComponentChrome
              metadata={tile}
              componentType={type}
              onResetFilter={hasReset ? noop : undefined}
              sourceFilterActive={filtering}
              showDragHandle={editor}
              extraActions={extras.length ? <>{extras}</> : undefined}
              compact={type === 'interactive'}
            >
              <Box className="depictio-fill depictio-guide-tile-body">
                <Body type={type} title={String(tile.title || STAND_IN_TITLE[type])} />
              </Box>
            </ComponentChrome>
          </Box>
        </SaveGroupContext.Provider>
      </InspectorProvider>

      <ActionLegend
        title="On hover, top right"
        hint={
          type === 'card'
            ? 'A card keeps its row on its bottom edge, under the number.'
            : 'Each icon has a tooltip; the row shows while the pointer is over the tile.'
        }
        actions={row}
        groupingColor={groupingColor}
      />
      <OwnLegend type={type} />
      <EditLegend actions={edit} />
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Legends
// ---------------------------------------------------------------------------

const LegendRow: React.FC<{
  glyph: React.ReactNode;
  label: string;
  meaning: string;
  when?: string;
  danger?: boolean;
}> = ({ glyph, label, meaning, when, danger }) => (
  <Group gap="sm" wrap="nowrap" align="flex-start" className="depictio-guide-legend-row">
    <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }} miw={52} justify="flex-start">
      {glyph}
    </Group>
    <Box style={{ minWidth: 0 }}>
      <Text size="sm" lh={1.4}>
        <Text span inherit fw={600} c={danger ? 'red' : undefined}>
          {label}
        </Text>{' '}
        — {meaning}
      </Text>
      {when && (
        <Text size="xs" c="dimmed" lh={1.35}>
          {when}
        </Text>
      )}
    </Box>
  </Group>
);

const LegendBlock: React.FC<{ title: string; hint?: string; children: React.ReactNode }> = ({
  title,
  hint,
  children,
}) => (
  <Box>
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} style={{ letterSpacing: '0.06em' }}>
      {title}
    </Text>
    {hint && (
      <Text size="xs" c="dimmed" mb={6}>
        {hint}
      </Text>
    )}
    <Stack gap={8} mt={hint ? 0 : 6}>
      {children}
    </Stack>
  </Box>
);

const ActionLegend: React.FC<{
  title: string;
  hint: string;
  actions: GuideRowAction[];
  groupingColor: string;
}> = ({ title, hint, actions, groupingColor }) => (
  <LegendBlock title={title} hint={hint}>
    <Box data-testid="guide-action-legend" className="depictio-guide-legend">
      {actions.map((a) => {
        let glyph: React.ReactNode = <Glyph style={a} legend />;
        if (a.key === 'group') {
          // The passive marker, then the action once there is a selection.
          glyph = (
            <>
              <Glyph style={a} color={groupingColor} legend />
              <Glyph style={a} color={groupingColor} variant="filled" legend />
            </>
          );
        } else if (a.key === 'reset') {
          glyph = (
            <>
              <Glyph style={a} legend />
              <Glyph style={a} variant="filled" legend />
            </>
          );
        }
        return (
          <LegendRow key={a.key} glyph={glyph} label={a.label} meaning={a.meaning} when={a.when} />
        );
      })}
    </Box>
  </LegendBlock>
);

const OwnLegend: React.FC<{ type: GuideTileType }> = ({ type }) => (
  <LegendBlock title="Inside the tile">
    <Box className="depictio-guide-legend">
      {ownControlsFor(type).map((c) => (
        <LegendRow
          key={c.label}
          glyph={
            <ActionIcon variant="default" size="sm" component="span" aria-hidden tabIndex={-1}>
              <Icon icon={c.icon} width={15} />
            </ActionIcon>
          }
          label={c.label}
          meaning={c.meaning}
        />
      ))}
    </Box>
  </LegendBlock>
);

/** The editor's grip, corner and ⋮ menu, drawn as the menu draws its items. */
const EditLegend: React.FC<{ actions: GuideEditAction[] }> = ({ actions }) => (
  <LegendBlock
    title="In the editor"
    hint="For authors: each tile gets a grip, a resize corner and a ⋮ menu at the end of its row."
  >
    <Paper withBorder radius="md" p="xs" className="depictio-guide-legend" data-testid="guide-edit-legend">
      {actions.map((a) => (
        <LegendRow
          key={a.key}
          glyph={
            a.key === 'drag' || a.key === 'resize' ? (
              <Glyph style={a} legend />
            ) : (
              <Box
                component="span"
                style={{
                  display: 'inline-flex',
                  width: 22,
                  justifyContent: 'center',
                  color: a.color ? `var(--mantine-color-${a.color}-filled)` : undefined,
                }}
              >
                <Icon icon={a.icon} width={14} />
              </Box>
            )
          }
          label={a.label}
          meaning={a.meaning}
          when={a.when}
          danger={a.color === 'red'}
        />
      ))}
    </Paper>
  </LegendBlock>
);

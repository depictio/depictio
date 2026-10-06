/**
 * The "component actions" demo: one of the dashboard's own components of the
 * kind picked, live, and the list of everything a reader or an author can do
 * to it.
 *
 * The tile is the real thing — `ComponentRenderer`, the real chrome, the real
 * renderer fetching its data — taken from the open tab when it has one of
 * that kind, else from a sibling tab. So every icon in its row works: the
 * metadata popover opens, fullscreen fills the screen, the table downloads,
 * the map shows its rows, a lasso filters and the reset clears it, the plot's
 * own toolbar zooms. Only a kind the whole dashboard lacks falls back to a
 * stand-in, and says so.
 *
 * The lists under the tile are connected to it: pointing at a line rings the
 * icon it describes on the tile, and a line whose icon this tile does not
 * carry says so. The editor's ⋮ menu is the real menu; in the Guide each of
 * its items says what it does instead of doing it.
 *
 * Everything the tile does stays here (see `GuideSandbox`): its selection is
 * the demo's own filter, a group saved from it is the demo's own group.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Box,
  CloseButton,
  Group,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  actionsTileRank,
  canCopyToTab,
  canHighlight,
  ComponentChrome,
  ComponentRenderer,
  componentTypeVisual,
  editActionsFor,
  groupFromSelectionFilter,
  isStripSection,
  ownControlsFor,
  rowActionsFor,
  supportsSelectionGrouping,
  uniqueGroupName,
  useGroupingColor,
  useGroupingColorVar,
  useInspectorControl,
} from 'depictio-react-core';
import type {
  FilterSectionSpec,
  GuideEditAction,
  GuideModel,
  GuideOwnControl,
  GuideRowAction,
  GuideTileType,
  InspectorControl,
  SaveGroupApi,
  SelectionGroup,
  StoredMetadata,
  TileActionStyle,
} from 'depictio-react-core';

import GridItemEditOverlay from '../../components/GridItemEditOverlay';
import { GuideSandbox } from '../GuideSandbox';
import { ringElements } from '../showMe';
import {
  pickedSource,
  useFamilyPick,
  type GuideComponentSource,
  type GuideFamily,
} from '../useGuideSources';
import { useDemoCards, useDemoFilters } from './demoState';

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

/** What the dashboard calls each kind, in a sentence. */
const NOUN: Record<GuideTileType, string> = {
  figure: 'figure',
  card: 'card',
  table: 'table',
  map: 'map',
  multiqc: 'MultiQC report',
  advanced_viz: 'advanced view',
  text: 'text tile',
  image: 'image grid',
  interactive: 'filter',
};

/** How tall the live tile is, as a tile of that kind usually is. `null`: as
 *  tall as its content (a card, a filter, a note). */
const TILE_HEIGHT: Record<GuideTileType, { base: number; sm: number } | null> = {
  figure: { base: 300, sm: 360 },
  table: { base: 320, sm: 360 },
  map: { base: 320, sm: 380 },
  multiqc: { base: 340, sm: 400 },
  advanced_viz: { base: 340, sm: 420 },
  image: { base: 300, sm: 340 },
  text: null,
  card: null,
  interactive: null,
};

/** Narrow kinds keep a tile's width rather than the demo's. */
const TILE_MAX_WIDTH: Partial<Record<GuideTileType, number>> = { card: 340, interactive: 380 };

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

const noop = () => undefined;

/** What an action does, said in place of doing it. */
export interface ActionNote {
  icon: string;
  label: string;
  meaning: string;
  color?: string;
}

/** What names the tile in the source line: its title, else for an untitled
 *  text tile its first words, else its kind. */
const titleOf = (m: StoredMetadata) => {
  if (m.title || m.column_name) return String(m.title || m.column_name);
  const body = typeof m.body === 'string' ? plainWords(m.body) : '';
  if (body) return body.length > 48 ? `${body.slice(0, 48).replace(/\s+\S*$/, '')}…` : body;
  return componentTypeVisual(m.component_type).label;
};

const whereFrom = (source: GuideComponentSource) =>
  source.here ? 'on this tab' : `from ${source.tabLabel}`;

/** Markdown down to its words: no marks, no link targets. */
const plainWords = (markdown: string) =>
  markdown
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/gm, '')
    .replace(/[#*_`>|~]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

// ---------------------------------------------------------------------------
// The tile and the lists, connected
// ---------------------------------------------------------------------------

const actionSelector = (key: string) => `[data-tile-action="${key}"]`;

const same = (a: Set<string>, b: Set<string>) => a.size === b.size && [...a].every((x) => b.has(x));

/**
 * What the live tile carries right now: its actions (by `data-tile-action`)
 * and the inside controls the lists name. Read off the DOM, because what a
 * tile shows depends on its data as much as its kind — the "load all" toggle
 * appears once a figure turns out sampled, the map's settings once it drew.
 */
function useTilePresence(
  tileRef: React.RefObject<HTMLDivElement | null>,
  controls: readonly GuideOwnControl[],
  resetKey: string,
): { actions: Set<string>; controls: Set<string> } {
  const [present, setPresent] = useState(() => ({
    actions: new Set<string>(),
    controls: new Set<string>(),
  }));
  useEffect(() => {
    const tile = tileRef.current;
    if (!tile) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      const actions = new Set(
        [...tile.querySelectorAll<HTMLElement>('[data-tile-action]')].map(
          (el) => el.dataset.tileAction ?? '',
        ),
      );
      const found = new Set(
        controls.filter((c) => c.target && tile.querySelector(c.target)).map((c) => c.label),
      );
      setPresent((prev) =>
        same(prev.actions, actions) && same(prev.controls, found)
          ? prev
          : { actions, controls: found },
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    read();
    const observer = new MutationObserver(schedule);
    observer.observe(tile, { subtree: true, childList: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [tileRef, controls, resetKey]);
  return present;
}

// ---------------------------------------------------------------------------
// The demo
// ---------------------------------------------------------------------------

export const ActionsDemo: React.FC<{
  model: GuideModel;
  family: GuideFamily;
  mode: 'view' | 'edit';
}> = ({ model, family, mode }) => {
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
  const [editor, setEditor] = useState(mode === 'edit');
  const [note, setNote] = useState<ActionNote | null>(null);

  const rank = useMemo(() => actionsTileRank(type), [type]);
  const source = pickedSource(family, useFamilyPick(family, rank));
  const sourceKey = source ? `${source.dashboardId}/${source.metadata.index}` : String(source);

  // A new tile starts clean.
  useEffect(() => {
    setNote(null);
  }, [sourceKey]);

  const selectable = Boolean(source && supportsSelectionGrouping(source.metadata, true));
  const row = rowActionsFor(type);
  // A select control counts only where selection is on.
  const own = useMemo(
    () => ownControlsFor(type).filter((c) => !c.selection || selectable),
    [type, selectable],
  );
  const ownListed = useMemo(() => ownControlsFor(type), [type]);
  const edit = editActionsFor(type, {
    hasSections: model.sections.foldable.length > 0 || model.sections.headings > 0,
    hasOtherTabs: model.tabs.count > 1,
  });

  const tileRef = useRef<HTMLDivElement | null>(null);
  const live = useTilePresence(tileRef, own, `${sourceKey}|${editor}|${analysis}`);
  const ring = useCallback((selector: string) => {
    const tile = tileRef.current;
    const el = tile?.querySelector<HTMLElement>(selector);
    if (!tile || !el) return;
    ringElements([el], {
      reveal: tile.querySelector<HTMLElement>('.depictio-component-chrome'),
      scroll: false,
    });
  }, []);

  const visual = componentTypeVisual(type);
  const options = types.map((t) => ({ value: t, label: SHORT_LABEL[t] }));
  const groupingColor = useGroupingColor();

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
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }} data-testid="guide-actions-source">
          <Icon icon={visual.icon} width={16} style={{ color: visual.color, flexShrink: 0 }} />
          <Text size="sm" c="dimmed" truncate>
            {source === undefined
              ? 'Looking for one…'
              : source === null
                ? `No ${NOUN[type]} in this dashboard: a stand-in shows its row`
                : `“${titleOf(source.metadata)}”, ${whereFrom(source)}`}
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
          <Switch
            size="xs"
            label="In the editor"
            checked={editor}
            onChange={(e) => setEditor(e.currentTarget.checked)}
          />
        </Group>
      </Group>

      <Box ref={tileRef} data-testid="guide-actions-tile">
        {source === undefined ? (
          <Skeleton h={TILE_HEIGHT[type]?.sm ?? 140} radius="md" />
        ) : source === null ? (
          <StandIn type={type} editor={editor} onNote={setNote} />
        ) : (
          <LiveTile
            key={sourceKey}
            type={type}
            source={source}
            family={family}
            analysis={analysis && selectable}
            editor={editor}
            onNote={setNote}
          />
        )}
      </Box>

      {note && (
        <Paper
          withBorder
          radius="md"
          p="xs"
          className="depictio-guide-note"
          data-testid="guide-actions-note"
          aria-live="polite"
        >
          <Group gap="sm" wrap="nowrap" align="flex-start">
            <Box
              component="span"
              style={{
                display: 'inline-flex',
                marginTop: 2,
                color: note.color ? `var(--mantine-color-${note.color}-filled)` : undefined,
              }}
            >
              <Icon icon={note.icon} width={16} />
            </Box>
            <Text size="sm" style={{ flex: 1 }}>
              <Text span inherit fw={600}>
                {note.label}
              </Text>{' '}
              — {note.meaning}{' '}
              <Text span inherit c="dimmed">
                From the Guide, nothing is changed.
              </Text>
            </Text>
            <CloseButton size="sm" onClick={() => setNote(null)} aria-label="Dismiss" />
          </Group>
        </Paper>
      )}

      <ActionLegend
        title="On hover, top right"
        hint={
          type === 'card'
            ? 'A card keeps its row on its bottom edge. Point at a line to find its icon on the tile.'
            : 'Each icon has a tooltip. Point at a line to find its icon on the tile.'
        }
        actions={row}
        groupingColor={groupingColor}
        live={live.actions}
        ring={ring}
      />
      <OwnLegend controls={ownListed} live={live.controls} selectable={selectable} ring={ring} />
      <EditLegend actions={edit} editor={editor} live={live.actions} ring={ring} />
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// The live tile
// ---------------------------------------------------------------------------

const LiveTile: React.FC<{
  type: GuideTileType;
  source: GuideComponentSource;
  family: GuideFamily;
  analysis: boolean;
  editor: boolean;
  onNote: (note: ActionNote) => void;
}> = ({ type, source, family, analysis, editor, onNote }) => {
  const [fontScale, setFontScale] = useState<number | undefined>(undefined);
  const metadata = useMemo<StoredMetadata>(
    () =>
      fontScale === undefined ? source.metadata : { ...source.metadata, font_scale: fontScale },
    [source.metadata, fontScale],
  );
  const sandboxMetadata = useMemo(() => [metadata], [metadata]);
  const { filters, settled, onFilterChange } = useDemoFilters(sandboxMetadata);
  const cards = useDemoCards(
    type === 'card' ? source.dashboardId : null,
    type === 'card' ? [metadata.index] : [],
    settled,
  );

  // Groups saved from the tile are the demo's: the save works, the reader's
  // own groups are untouched.
  const [groups, setGroups] = useState<SelectionGroup[]>([]);
  const groupsRef = useRef(groups);
  groupsRef.current = groups;
  const saveGroup = useMemo<SaveGroupApi>(
    () => ({
      groups,
      createGroup: (filter, name, color) => {
        const created = groupFromSelectionFilter(
          filter,
          uniqueGroupName(name, groupsRef.current),
          color,
        );
        if (created) {
          setGroups((prev) => [...prev, created]);
          onNote({
            icon: 'mdi:select-group',
            label: `Saved “${created.name}”`,
            meaning: `${created.values.length} values, kept in the Guide only. The Analysis part below compares groups.`,
          });
        }
        return created;
      },
      clearSelection: onFilterChange,
      analysisEngaged: analysis,
    }),
    [groups, onFilterChange, analysis, onNote],
  );

  // The inspect action, where the app has the inspector on: in the Guide it
  // says what it does.
  const appInspector = useInspectorControl();
  const inspector = useMemo<InspectorControl | null>(
    () =>
      appInspector
        ? {
            selectedId: null,
            select: () =>
              onNote({
                icon: 'mdi:dock-right',
                label: 'Inspect',
                meaning: 'Opens the component in the inspector beside the page.',
                color: 'grape',
              }),
          }
        : null,
    [appInspector, onNote],
  );

  const menu = editor ? (
    <EditMenu
      source={source}
      family={family}
      metadata={metadata}
      onNote={onNote}
      onFontScale={setFontScale}
    />
  ) : undefined;

  const height = TILE_HEIGHT[type];
  return (
    <GuideSandbox metadata={sandboxMetadata} saveGroup={saveGroup} inspector={inspector}>
      <Box
        className="depictio-guide-demo-tile"
        data-tile-type={type}
        h={height ?? undefined}
        maw={TILE_MAX_WIDTH[type]}
        mih={type === 'card' ? 130 : undefined}
      >
        <div className="depictio-guide-demo-cell">
          <ComponentRenderer
            metadata={metadata}
            dashboardId={source.dashboardId}
            filters={filters}
            onFilterChange={onFilterChange}
            cardValue={cards.values[metadata.index]}
            cardSecondaryValues={cards.secondary[metadata.index]}
            cardLoading={cards.loading}
            extraActions={menu}
            showDragHandle={editor}
          />
        </div>
      </Box>
    </GuideSandbox>
  );
};

/** The editor's real ⋮ menu, its items saying what they do instead. */
const EditMenu: React.FC<{
  source: GuideComponentSource;
  family: GuideFamily;
  metadata: StoredMetadata;
  onNote: (note: ActionNote) => void;
  onFontScale: (scale: number) => void;
}> = ({ source, family, metadata, onNote, onFontScale }) => {
  const type = metadata.component_type as GuideTileType;
  const meaning = useMemo(() => new Map(editActionsFor(type).map((a) => [a.key, a])), [type]);
  const say = (key: GuideEditAction['key'], label?: string) => {
    const a = meaning.get(key);
    if (a) onNote({ icon: a.icon, label: label ?? a.label, meaning: a.meaning, color: a.color });
  };
  const owner = family.docFor(source.dashboardId);
  const sections = ((owner?.grid_sections as FilterSectionSpec[] | undefined) ?? []).filter(
    (s) => !isStripSection(s),
  );
  const otherTabs = family.tabs.filter((t) => t.dashboard_id !== source.dashboardId);
  return (
    <GridItemEditOverlay
      dashboardId={source.dashboardId}
      componentId={metadata.index}
      editMode
      componentType={type}
      onEdit={() => say('edit')}
      onDelete={() => say('delete')}
      onDuplicate={() => say('duplicate')}
      sections={sections}
      currentSection={(metadata.section as string | undefined) ?? null}
      onMoveToSection={(_id, section) =>
        say('move-section', section ? `Move to “${section}”` : 'Out of its section')
      }
      fontScale={typeof metadata.font_scale === 'number' ? metadata.font_scale : undefined}
      onFontScale={(_id, scale) => {
        // A real change, to the copy only: the figure redraws at that size.
        onFontScale(scale);
        say('font-size', `Font size ${Math.round(scale * 100)}%`);
      }}
      copyTargets={canCopyToTab(metadata) ? otherTabs : undefined}
      onCopyToTab={(_id, tab) => say('copy-tab', `Copy to ${family.labelOf(tab)}`)}
      highlightTargets={canHighlight(metadata) ? otherTabs : undefined}
      onHighlightOnTab={(_id, tab) => say('highlight', `Highlight on ${family.labelOf(tab)}`)}
    />
  );
};

// ---------------------------------------------------------------------------
// The stand-in, for a kind the dashboard does not have
// ---------------------------------------------------------------------------

const StandIn: React.FC<{
  type: GuideTileType;
  editor: boolean;
  onNote: (note: ActionNote) => void;
}> = ({ type, editor, onNote }) => {
  const tile = useMemo(
    () =>
      ({
        index: `guide-stand-in:${type}`,
        component_type: type,
        title: STAND_IN_TITLE[type],
      }) as StoredMetadata,
    [type],
  );
  const sandboxMetadata = useMemo(() => [tile], [tile]);
  const groupingColorVar = useGroupingColorVar();
  const row = rowActionsFor(type);
  const extras: React.ReactNode[] = [];
  for (const a of row) {
    if (a.key === 'settings' || a.key === 'data' || a.key === 'loadAll') {
      extras.push(
        <span key={a.key} data-tile-action={a.key} style={{ display: 'inline-flex' }}>
          <Glyph style={a} />
        </span>,
      );
    }
  }
  if (editor) {
    const items = editActionsFor(type).filter((a) => a.key !== 'drag' && a.key !== 'resize');
    extras.push(
      <Tooltip key="menu" label="The editor's menu" withArrow>
        <ActionIcon
          variant="subtle"
          size="sm"
          data-tile-action="menu"
          aria-label="Component actions"
          onClick={() =>
            onNote({
              icon: 'tabler:dots-vertical',
              label: 'Component actions',
              meaning: `${items.map((a) => a.label).join(', ')}.`,
            })
          }
        >
          <Icon icon="tabler:dots-vertical" width={16} />
        </ActionIcon>
      </Tooltip>,
    );
  }
  const tall = TILE_HEIGHT[type] !== null;
  return (
    <GuideSandbox metadata={sandboxMetadata}>
      <Box
        className="depictio-guide-demo-tile"
        h={tall ? 260 : 140}
        maw={TILE_MAX_WIDTH[type] ?? 560}
        style={{ '--depictio-grouping-color': groupingColorVar } as React.CSSProperties}
      >
        <ComponentChrome
          metadata={tile}
          componentType={type}
          onResetFilter={row.some((a) => a.key === 'reset') ? noop : undefined}
          showDragHandle={editor}
          extraActions={extras.length ? <>{extras}</> : undefined}
          compact={type === 'interactive'}
        >
          <Box className="depictio-fill depictio-guide-tile-body">
            <Body type={type} title={STAND_IN_TITLE[type]} />
          </Box>
        </ComponentChrome>
      </Box>
    </GuideSandbox>
  );
};

/** What a stand-in's body looks like, per kind. */
const Body: React.FC<{ type: GuideTileType; title: string }> = ({ type, title }) => {
  const bars = (heights: number[]) => (
    <Box className="depictio-guide-bars" pt={8} pb={8} style={{ height: '100%' }}>
      {heights.map((h, i) => (
        <span key={i} style={{ height: `${h}%` }} />
      ))}
    </Box>
  );
  let inner: React.ReactNode;
  switch (type) {
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
    case 'card':
      inner = (
        <Text size="xl" fw={700} c="var(--mantine-primary-color-filled)">
          —
        </Text>
      );
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

/** An action's icon in its real button: subtle, `sm`, a 16px glyph. */
const Glyph: React.FC<{
  style: TileActionStyle;
  color?: string;
  variant?: 'subtle' | 'filled';
  /** In a legend row the label is beside it: no tooltip, out of the tab order. */
  legend?: boolean;
}> = ({ style, color, variant = 'subtle', legend }) => {
  const icon = (
    <ActionIcon
      variant={variant}
      color={color ?? style.color}
      size="sm"
      aria-label={legend ? undefined : style.label}
      aria-hidden={legend || undefined}
      tabIndex={legend ? -1 : undefined}
      component={legend ? 'span' : 'button'}
      style={legend ? { cursor: 'inherit' } : undefined}
    >
      <Icon icon={style.icon} width={16} height={16} />
    </ActionIcon>
  );
  return legend ? (
    icon
  ) : (
    <Tooltip label={style.label} withArrow>
      {icon}
    </Tooltip>
  );
};

// ---------------------------------------------------------------------------
// Legends
// ---------------------------------------------------------------------------

/**
 * One line of a list. Live, it rings its icon on the tile when pointed at,
 * focused or clicked; otherwise it is dimmed and says the tile has none.
 */
const LegendRow: React.FC<{
  glyph: React.ReactNode;
  label: string;
  meaning: string;
  when?: string;
  danger?: boolean;
  /** Rings the matching element on the tile; absent when it has none. */
  onPoint?: () => void;
  absentNote?: string;
  testId?: string;
}> = ({ glyph, label, meaning, when, danger, onPoint, absentNote, testId }) => {
  const live = Boolean(onPoint);
  const aside = [when, !live ? absentNote : null].filter(Boolean).join(' · ');
  return (
    <Group
      gap="sm"
      wrap="nowrap"
      align="flex-start"
      className={'depictio-guide-legend-row' + (live ? ' is-live' : ' is-absent')}
      role={live ? 'button' : undefined}
      tabIndex={live ? 0 : undefined}
      aria-label={live ? `${label}: show it on the tile` : undefined}
      onMouseEnter={onPoint}
      onFocus={onPoint}
      onClick={onPoint}
      onKeyDown={(e) => {
        if (live && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onPoint?.();
        }
      }}
      data-live={live || undefined}
      data-testid={testId}
    >
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
        {aside && (
          <Text size="xs" c="dimmed" lh={1.35}>
            {aside}
          </Text>
        )}
      </Box>
    </Group>
  );
};

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
  live: Set<string>;
  ring: (selector: string) => void;
}> = ({ title, hint, actions, groupingColor, live, ring }) => (
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
          <LegendRow
            key={a.key}
            glyph={glyph}
            label={a.label}
            meaning={a.meaning}
            when={a.when}
            onPoint={live.has(a.key) ? () => ring(actionSelector(a.key)) : undefined}
            absentNote="not on this one"
            testId={`guide-legend-${a.key}`}
          />
        );
      })}
    </Box>
  </LegendBlock>
);

const OwnLegend: React.FC<{
  controls: readonly GuideOwnControl[];
  live: Set<string>;
  selectable: boolean;
  ring: (selector: string) => void;
}> = ({ controls, live, selectable, ring }) => (
  <LegendBlock title="Inside the tile">
    <Box className="depictio-guide-legend">
      {controls.map((c) => (
        <LegendRow
          key={c.label}
          glyph={
            <ActionIcon variant="default" size="sm" component="span" aria-hidden tabIndex={-1}>
              <Icon icon={c.icon} width={15} />
            </ActionIcon>
          }
          label={c.label}
          meaning={c.meaning}
          onPoint={c.target && live.has(c.label) ? () => ring(c.target as string) : undefined}
          absentNote={
            c.selection && !selectable
              ? 'selection is off on this one'
              : c.target
                ? 'not on this one'
                : undefined
          }
        />
      ))}
    </Box>
  </LegendBlock>
);

/** The editor's grip, corner and ⋮ menu, drawn as the menu draws its items. */
const EditLegend: React.FC<{
  actions: GuideEditAction[];
  editor: boolean;
  live: Set<string>;
  ring: (selector: string) => void;
}> = ({ actions, editor, live, ring }) => (
  <LegendBlock
    title="In the editor"
    hint={
      editor
        ? 'A grip, a resize corner and a ⋮ menu at the end of the row. In the Guide, its items say what they do.'
        : 'For authors: a grip, a resize corner and a ⋮ menu. Turn on “In the editor” to try the menu.'
    }
  >
    <Paper withBorder radius="md" p="xs" className="depictio-guide-legend" data-testid="guide-edit-legend">
      {actions.map((a) => {
        const key = a.key === 'drag' ? 'drag' : a.key === 'resize' ? null : 'menu';
        return (
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
            onPoint={editor && key && live.has(key) ? () => ring(actionSelector(key)) : undefined}
            absentNote={a.key === 'resize' ? "on the editor's grid" : undefined}
          />
        );
      })}
    </Paper>
  </LegendBlock>
);

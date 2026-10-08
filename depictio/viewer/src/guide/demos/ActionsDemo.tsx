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
 * Some icons depend on the tile rather than its kind. The catalog's and the
 * author's note the demo draws on its copy where the tile itself would not
 * (see `demoCopyOf`), each opening to say so. The others it leaves to the
 * dashboard, so that no icon on the tile is one that does nothing here: the
 * inspector's shows only where the server has the inspector on, and where it
 * is off the list leaves its line out (`useDemoInspector`); "load all" shows
 * where the tile has more to load — a table's copy pages by fewer rows, and
 * its own "load all" loads them — and where it has not, its line says so.
 * Advanced views differ the most, so that kind offers two.
 *
 * Everything the tile does stays here (see `GuideSandbox`): its selection is
 * the demo's own filter, a group saved from it is the demo's own group.
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Box,
  CloseButton,
  Collapse,
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
  UnstyledButton,
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
  resolveFigureStyle,
  rowActionsFor,
  supportsSelectionGrouping,
  TILE_ACTION_STYLE,
  uniqueGroupName,
  useDashboardLoadSummary,
  useGroupingColor,
  useGroupingColorVar,
  useInspectorControl,
} from 'depictio-react-core';
import type {
  CatalogSource,
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
  TileActionStyleKey,
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

/** An advanced view as the switch between the two names it: its title, else
 *  its kind, short enough for two to sit side by side on a phone. */
const viewName = (m: StoredMetadata) => {
  const name = String(m.title ?? '').trim() || String(m.viz_kind ?? 'view').replace(/_/g, ' ');
  return name.length > 22 ? `${name.slice(0, 22).replace(/\s+\S*$/, '')}…` : name;
};

// ---------------------------------------------------------------------------
// The demo's copy of the tile
// ---------------------------------------------------------------------------

/**
 * What the catalog icon opens on a copy whose tile did not come from the
 * tools catalog. The icon exists only on such tiles, so the Guide marks its
 * copy to show where it sits; the popover says that is all it is.
 */
const GUIDE_CATALOG_SOURCE: CatalogSource = {
  description:
    'In the Guide only: a component added from the tools catalog names here the tool and output it came from, and the use: line that adds it to a YAML dashboard.',
};

/** The same for the author's note, whose icon shows only where there is one. */
const GUIDE_DESCRIPTION =
  "In the Guide only: the author's note on what the component shows. This one has none, so the Guide wrote this.";

/** Rows a demo table pages by, at most: few enough that most tables span the
 *  five pages that make TableRenderer offer "load all". */
const DEMO_PAGE_SIZE = 10;

/**
 * The tile as the demo draws it: a copy of its metadata, never the original,
 * carrying what makes the chrome draw the icons that depend on the tile — a
 * catalog origin, an author's note, a page size a table outgrows — where the
 * original has none. A figure or a view draws what it drew before (the
 * server renders a figure from the stored original); a table pages by fewer
 * rows, and its "load all" then loads them all, as on the canvas.
 */
function demoCopyOf(m: StoredMetadata, fontScale?: number): StoredMetadata {
  const copy: StoredMetadata = { ...m };
  if (fontScale !== undefined) copy.font_scale = fontScale;
  if (!m.catalog_source) copy.catalog_source = GUIDE_CATALOG_SOURCE;
  // Outside the minimal style an advanced view prints its note under its
  // title: there it would be text on the tile, not an icon.
  const noted = typeof m.description === 'string' && m.description.trim() !== '';
  if (
    !noted &&
    (m.component_type !== 'advanced_viz' || resolveFigureStyle(m.figure_style) === 'minimal')
  ) {
    copy.description = GUIDE_DESCRIPTION;
  }
  if (m.component_type === 'table') {
    const own = typeof m.page_size === 'number' && m.page_size > 0 ? m.page_size : Infinity;
    copy.page_size = Math.min(own, DEMO_PAGE_SIZE);
  }
  return copy;
}

/**
 * The inspect action, where the server has the inspector on: on a demo tile
 * it says what it does rather than opening the app's inspector on a copy.
 * Where the inspector is off, `null`: the sandbox then draws no inspect icon,
 * as the dashboard draws none, and the list leaves its line out.
 */
function useDemoInspector(onNote: (note: ActionNote) => void): InspectorControl | null {
  const on = Boolean(useInspectorControl());
  return useMemo<InspectorControl | null>(
    () =>
      on
        ? {
            selectedId: null,
            select: () =>
              onNote({
                icon: TILE_ACTION_STYLE.inspect.icon,
                label: TILE_ACTION_STYLE.inspect.label,
                meaning: 'Opens the component in the inspector beside the page.',
                color: TILE_ACTION_STYLE.inspect.color,
              }),
          }
        : null,
    [on, onNote],
  );
}

/** Why a drawn tile of `type` has no "load all": it shows all there is. */
const LOAD_ALL_ABSENT: Partial<Record<GuideTileType, string>> = {
  figure: 'this one draws all of its points',
  table: 'this one fits in a few pages',
  advanced_viz: 'this one draws all of its data',
};

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

/**
 * Says whether the tile in the same sandbox has drawn, from the load registry
 * its renderer reports to (`GuideSandbox` mounts one per demo). Rendered
 * inside the sandbox, which the tile's own hooks sit outside of.
 */
const DrawnProbe: React.FC<{
  metadata: StoredMetadata[];
  onDrawn: (drawn: boolean) => void;
}> = ({ metadata, onDrawn }) => {
  const drawn = useDashboardLoadSummary(metadata, false).ready > 0;
  useEffect(() => onDrawn(drawn), [drawn, onDrawn]);
  return null;
};

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
  // The lists past the row fold, closed until asked for.
  const [ownOpen, setOwnOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  const rank = useMemo(() => actionsTileRank(type), [type]);
  const first = pickedSource(family, useFamilyPick(family, rank));
  // Advanced views: a second one, for the rows behind the table icon, which
  // the first (picked for its selection, often a tree) may not list.
  const firstView = type === 'advanced_viz' && first ? first.metadata : null;
  const secondRank = useMemo(
    () => actionsTileRank('advanced_viz', { secondTo: firstView }),
    [firstView],
  );
  const second = pickedSource(
    family,
    useFamilyPick(family, secondRank, { enabled: firstView !== null }),
  );
  const views = firstView && first && second ? ([first, second] as const) : null;
  const [view, setView] = useState<0 | 1>(0);
  const source = views ? views[view] : first;
  const sourceKey = source ? `${source.dashboardId}/${source.metadata.index}` : String(source);
  // Whether the live tile has drawn: until then, an action its data decides
  // ("load all") cannot be said to be missing.
  const [drawn, setDrawn] = useState(false);

  // A new tile starts clean.
  useEffect(() => {
    setNote(null);
    setDrawn(false);
  }, [sourceKey]);

  const selectable = Boolean(source && supportsSelectionGrouping(source.metadata, true));
  const inspector = Boolean(useInspectorControl());
  const row = rowActionsFor(type, { inspector });
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

  // Why a line of the row has no icon on this tile, where more can be said
  // than that it has none.
  const minimal = Boolean(source) && resolveFigureStyle(source?.metadata.figure_style) === 'minimal';
  const absentNote = (key: TileActionStyleKey) => {
    if (key === 'group' || (key === 'reset' && type !== 'interactive')) {
      if (!selectable) return 'selection is off on this one';
      if (key === 'group' && !analysis) return 'turn on “Analysis on” to see it';
    }
    if (key === 'description' && type === 'advanced_viz' && !minimal) {
      return 'in its style, a view prints it under its title';
    }
    if (key === 'loadAll' && drawn && LOAD_ALL_ABSENT[type]) return LOAD_ALL_ABSENT[type];
    return 'not on this one';
  };

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

      {views && (
        <Group gap="xs" wrap="nowrap" data-testid="guide-actions-views" style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            Two views:
          </Text>
          <SegmentedControl
            size="xs"
            value={String(view)}
            onChange={(v) => setView(v === '1' ? 1 : 0)}
            data={views.map((s, i) => ({ value: String(i), label: viewName(s.metadata) }))}
            aria-label="Which advanced view"
          />
        </Group>
      )}

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
            onChange={(e) => {
              const on = e.currentTarget.checked;
              setEditor(on);
              // Turned on to try the menu: its list opens with it.
              if (on) setEditOpen(true);
            }}
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
            onDrawn={setDrawn}
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
        absentNote={absentNote}
        ring={ring}
      />
      <OwnLegend
        controls={ownListed}
        live={live.controls}
        selectable={selectable}
        ring={ring}
        fold={{ open: ownOpen, onToggle: () => setOwnOpen((o) => !o) }}
      />
      <EditLegend
        actions={edit}
        editor={editor}
        live={live.actions}
        ring={ring}
        fold={{ open: editOpen, onToggle: () => setEditOpen((o) => !o) }}
      />
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
  onDrawn: (drawn: boolean) => void;
}> = ({ type, source, family, analysis, editor, onNote, onDrawn }) => {
  const [fontScale, setFontScale] = useState<number | undefined>(undefined);
  const metadata = useMemo<StoredMetadata>(
    () => demoCopyOf(source.metadata, fontScale),
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

  const inspector = useDemoInspector(onNote);

  // The row's only addition is the editor's ⋮ menu. "Load all" is the
  // renderer's own, once its data turns out reduced: a sampled figure or
  // view, a table paging deep (the copy pages by `DEMO_PAGE_SIZE`). Where the
  // tile has none, the list says why rather than the Guide drawing one that
  // could only pretend to load.
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
      <DrawnProbe metadata={sandboxMetadata} onDrawn={onDrawn} />
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
      onOpenHistory={() => say('history')}
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
      demoCopyOf({
        index: `guide-stand-in:${type}`,
        component_type: type,
        title: STAND_IN_TITLE[type],
      } as StoredMetadata),
    [type],
  );
  const sandboxMetadata = useMemo(() => [tile], [tile]);
  const inspector = useDemoInspector(onNote);
  const groupingColorVar = useGroupingColorVar();
  const row = rowActionsFor(type, { inspector: inspector !== null });
  const extras: React.ReactNode[] = [];
  // What a renderer adds to the row, drawn as its icons: with no tile of the
  // kind to act on, each says what it does when tried.
  for (const a of row) {
    if (a.key === 'settings' || a.key === 'data' || a.key === 'loadAll') {
      extras.push(
        <span key={a.key} data-tile-action={a.key} style={{ display: 'inline-flex' }}>
          <Glyph
            style={a}
            onClick={() =>
              onNote({
                icon: a.icon,
                label: a.label,
                meaning: `${a.meaning} This dashboard has no ${NOUN[type]} to show it on.`,
                color: a.color,
              })
            }
          />
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
    <GuideSandbox metadata={sandboxMetadata} inspector={inspector}>
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
  onClick?: () => void;
}> = ({ style, color, variant = 'subtle', legend, onClick }) => {
  const icon = (
    <ActionIcon
      variant={variant}
      color={color ?? style.color}
      size="sm"
      onClick={onClick}
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

/** A list that folds under its title, and whether it is open. */
interface LegendFold {
  open: boolean;
  onToggle: () => void;
}

const LegendBlock: React.FC<{
  title: string;
  hint?: string;
  /** Folds the list under its title; without it the list is always open. */
  fold?: LegendFold;
  children: React.ReactNode;
}> = ({ title, hint, fold, children }) => {
  const bodyId = useId();
  const heading = (
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} style={{ letterSpacing: '0.06em' }}>
      {title}
    </Text>
  );
  const body = (
    <>
      {hint && (
        <Text size="xs" c="dimmed" mb={6}>
          {hint}
        </Text>
      )}
      <Stack gap={8} mt={hint ? 0 : 6}>
        {children}
      </Stack>
    </>
  );
  if (!fold) {
    return (
      <Box>
        {heading}
        {body}
      </Box>
    );
  }
  return (
    <Box>
      <UnstyledButton
        className="depictio-guide-legend-toggle"
        onClick={fold.onToggle}
        aria-expanded={fold.open}
        aria-controls={bodyId}
      >
        <Group gap={2} wrap="nowrap">
          <Icon icon="mdi:chevron-right" width={16} className="depictio-guide-legend-chevron" />
          {heading}
        </Group>
      </UnstyledButton>
      <Collapse in={fold.open} id={bodyId}>
        {body}
      </Collapse>
    </Box>
  );
};

const ActionLegend: React.FC<{
  title: string;
  hint: string;
  actions: GuideRowAction[];
  groupingColor: string;
  live: Set<string>;
  /** What a line says when its icon is not on the tile. */
  absentNote: (key: TileActionStyleKey) => string;
  ring: (selector: string) => void;
}> = ({ title, hint, actions, groupingColor, live, absentNote, ring }) => (
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
            absentNote={absentNote(a.key)}
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
  fold: LegendFold;
}> = ({ controls, live, selectable, ring, fold }) => (
  <LegendBlock title="Inside the tile" fold={fold}>
    <Box className="depictio-guide-legend" data-testid="guide-own-legend">
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
  fold: LegendFold;
}> = ({ actions, editor, live, ring, fold }) => (
  <LegendBlock
    title="In the editor"
    fold={fold}
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

/**
 * The dashboard Guide: one page on how to move around a dashboard, filter it
 * and read its components, that a reader can open at any time.
 *
 * Not a tour. There are no steps and nothing to dismiss: the page is a column
 * of parts, each a short explanation, a small working demo, and a "Show me"
 * that rings, in that demo, the control the part is about. The reader never
 * steers the Guide nor leaves it to find something. The explanations are
 * generic; what fills them — the tabs, the sections, the filters, the actions
 * — is read from the tab the Guide was opened on (`buildGuideModel`), and the
 * demos are built from the dashboard's own components (`useGuideSources`), so
 * the Guide never describes a control the dashboard does not have.
 *
 * The page covers the tab's canvas only: the sidebar, the header and the
 * filter panel stay beside it.
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Container,
  Group,
  List,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { genomeConfigOf, TextRenderer, useCommentsControl } from 'depictio-react-core';
import { paletteVar } from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  GuideModel,
  PersistentSection,
  StoredMetadata,
} from 'depictio-react-core';

import { DemoFrame, TabPillsDemo, YourViewDemo } from './GuideDemos';
import { ActionsDemo } from './demos/ActionsDemo';
import { AnalysisDemo } from './demos/AnalysisDemo';
import { CommentsDemo, type CommentsRole } from './demos/CommentsDemo';
import { GenomeDemo, GenomeWhere } from './demos/GenomeDemo';
import { LiveFilterDemo, LiveFilterDemoSkeleton } from './demos/LiveFilterDemo';
import { SectionsDemo } from './demos/SectionsDemo';
import { VersionsDemo } from './demos/VersionsDemo';
import { findDemoTargets, showDemoTarget, type GuideTarget } from './showMe';
import { useGuideSources } from './useGuideSources';

export interface DashboardGuideProps {
  model: GuideModel;
  /** The open tab. */
  dashboardId: string;
  dashboard: DashboardData;
  /** The open tab's canvas components, as drawn. */
  components: readonly StoredMetadata[];
  /** The tab family, sidebar order, main tab first. */
  tabs: readonly DashboardSummary[];
  /** The family's pinned sections, whichever tab owns them. */
  persistentSections: readonly PersistentSection[];
  /** The dashboard's name: the main tab's title. */
  dashboardName: string;
  /** The tab the Guide was opened on. */
  tabName: string;
  /** The author's note (markdown), '' for none. */
  intro: string;
  mode: 'view' | 'edit';
  /** The reader can edit this dashboard (owners and editors). Defaults to
   *  `mode === 'edit'`; the viewer passes its own check. */
  canEdit?: boolean;
  onClose: () => void;
  /** Opens the dashboard settings on "Your view". */
  onOpenYourView: () => void;
}

// ---------------------------------------------------------------------------
// Wording helpers
// ---------------------------------------------------------------------------

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "A, B and C", or "A, B, C and 4 more" past `max`. */
function listNames(names: readonly string[], max = 4): string {
  if (names.length === 0) return '';
  const shown = names.slice(0, names.length > max ? max - 1 : max);
  const rest = names.length - shown.length;
  const head = rest > 0 ? [...shown, `${rest} more`] : shown;
  return head.length === 1 ? head[0] : `${head.slice(0, -1).join(', ')} and ${head[head.length - 1]}`;
}

// ---------------------------------------------------------------------------
// The layer's place: over the canvas, and only the canvas
// ---------------------------------------------------------------------------

type LayerBox = { top: number; left: number; width: number; height: number };

/** The tab's canvas: the scroll container every tile lives in. */
const CANVAS_SELECTOR = '[data-testid="dashboard-content"]';

/**
 * The canvas's box on screen, followed as the sidebar slides, the filter panel
 * folds or the window resizes (each changes the canvas's size, which is what
 * the observer sees). Null until measured, or with no canvas on the page: the
 * stylesheet's AppShell offsets place the layer then.
 */
function useCanvasBox(): LayerBox | null {
  const [box, setBox] = useState<LayerBox | null>(null);
  useLayoutEffect(() => {
    let canvas = document.querySelector<HTMLElement>(CANVAS_SELECTOR);
    if (!canvas) return;
    const measure = () => {
      if (!canvas?.isConnected) canvas = document.querySelector<HTMLElement>(CANVAS_SELECTOR);
      if (!canvas) return;
      const r = canvas.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      setBox((prev) =>
        prev &&
        prev.top === r.top &&
        prev.left === r.left &&
        prev.width === r.width &&
        prev.height === r.height
          ? prev
          : { top: r.top, left: r.left, width: r.width, height: r.height },
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  return box;
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

interface ShowMeSpec {
  target: GuideTarget;
  label: string;
}

/**
 * Whether the demo in `part` has what `target` points at. Polled: the demos
 * mount their tiles as the data arrives, and a "Show me" offered before then
 * would ring nothing.
 */
function useDemoHas(
  part: React.RefObject<HTMLElement | null>,
  target: GuideTarget | undefined,
): boolean {
  const [has, setHas] = useState(false);
  useEffect(() => {
    if (!target) return;
    const tick = () => {
      const demo = part.current?.querySelector('.depictio-guide-demo');
      setHas(Boolean(demo && findDemoTargets(target, demo).length > 0));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [part, target]);
  return has;
}

interface PartProps {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  points: React.ReactNode[];
  demo?: React.ReactNode;
  demoLabel?: string;
  /** A small aside under the demo. */
  note?: React.ReactNode;
  /** The part's "Show me", in its header: rings that thing in the demo. */
  showMe?: ShowMeSpec;
  /** Secondary actions, under the demo. */
  footer?: React.ReactNode;
}

/** One part of the Guide: what it is about, a few lines, a demo, Show me. */
const GuidePart: React.FC<PartProps> = ({
  id,
  icon,
  title,
  subtitle,
  points,
  demo,
  demoLabel,
  note,
  showMe,
  footer,
}) => {
  const ref = useRef<HTMLElement | null>(null);
  const showMeHere = useDemoHas(ref, demo ? showMe?.target : undefined);
  const shownPoints = points.filter(Boolean);
  return (
    <Paper
      ref={ref}
      component="section"
      id={`guide-${id}`}
      aria-labelledby={`guide-${id}-title`}
      withBorder
      radius="lg"
      p={{ base: 'md', sm: 'lg' }}
      style={{ scrollMarginTop: 16 }}
      data-testid={`guide-part-${id}`}
    >
      <Stack gap="md">
        <Group gap="md" wrap="wrap" align="flex-start" justify="space-between">
          <Group gap="md" wrap="nowrap" align="flex-start" style={{ flex: '1 1 260px', minWidth: 0 }}>
            <ThemeIcon size={40} radius="md" variant="light" style={{ flexShrink: 0 }}>
              <Icon icon={icon} width={22} height={22} />
            </ThemeIcon>
            <Box style={{ minWidth: 0 }}>
              <Title order={2} size="h4" id={`guide-${id}-title`} lh={1.25}>
                {title}
              </Title>
              <Text size="sm" c="dimmed" lh={1.4}>
                {subtitle}
              </Text>
            </Box>
          </Group>
          {showMe && showMeHere && (
            <Button
              variant="light"
              size="sm"
              radius="md"
              leftSection={<Icon icon="mdi:crosshairs-gps" width={18} />}
              onClick={() => {
                const frame = ref.current?.querySelector('.depictio-guide-demo');
                if (frame) showDemoTarget(showMe.target, frame);
              }}
              data-testid={`guide-show-${showMe.target}`}
              style={{ flexShrink: 0 }}
            >
              {showMe.label}
            </Button>
          )}
        </Group>
        {shownPoints.length > 0 && (
          <List
            size="sm"
            spacing={6}
            icon={
              <Icon
                icon="mdi:circle-small"
                width={18}
                style={{ color: 'var(--mantine-primary-color-filled)', display: 'block' }}
              />
            }
            styles={{ itemWrapper: { alignItems: 'flex-start' }, itemIcon: { marginTop: 1 } }}
          >
            {shownPoints.map((p, i) => (
              <List.Item key={i}>{p}</List.Item>
            ))}
          </List>
        )}
        {demo && <DemoFrame label={demoLabel}>{demo}</DemoFrame>}
        {note}
        {footer && (
          <Group gap="sm" wrap="wrap">
            {footer}
          </Group>
        )}
      </Stack>
    </Paper>
  );
};

/** An inline mention of a control, drawn as the control's own icon. */
const Kbd: React.FC<{ icon?: string; color?: string; children: React.ReactNode }> = ({
  icon,
  color,
  children,
}) => (
  <Text span inherit fw={600} style={{ whiteSpace: 'nowrap' }}>
    {icon && (
      <Icon
        icon={icon}
        width={14}
        style={{
          verticalAlign: '-2px',
          marginRight: 3,
          color: color ? paletteVar(color, 'filled') : 'var(--mantine-primary-color-filled)',
        }}
      />
    )}
    {children}
  </Text>
);

/** A one-line aside, under a demo. */
const Note: React.FC<{ children: React.ReactNode; testId?: string }> = ({ children, testId }) => (
  <Group gap={6} wrap="nowrap" align="flex-start" data-testid={testId}>
    <Icon
      icon="mdi:information-outline"
      width={15}
      style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0, marginTop: 2 }}
    />
    <Text size="xs" c="dimmed" lh={1.45}>
      {children}
    </Text>
  </Group>
);

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

const DashboardGuide: React.FC<DashboardGuideProps> = ({
  model,
  dashboardId,
  dashboard,
  components,
  tabs: family,
  persistentSections,
  dashboardName,
  tabName,
  intro,
  mode,
  canEdit,
  onClose,
  onOpenYourView,
}) => {
  const sources = useGuideSources({
    dashboardId,
    dashboard,
    components,
    tabs: family,
    persistentSections,
  });
  const canvasBox = useCanvasBox();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);

  // Arriving on the Guide moves focus to its title, so a screen reader starts
  // at the top of the page rather than on the control that opened it.
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, []);

  // Esc closes the Guide, unless something on top of it (a menu, the
  // settings, a select's list) is the thing Esc is for. In the capture phase:
  // the dashboard's own key handlers stop Escape from bubbling to the window.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // A demo tile in fullscreen: Esc is the browser's, to leave it.
      if (document.fullscreenElement) return;
      if (document.querySelector('[role="dialog"], [role="menu"], [role="listbox"]')) return;
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const introMetadata = useMemo(
    () => ({ index: '', component_type: 'text', body: intro }) as unknown as StoredMetadata,
    [intro],
  );

  const { tabs, sections, filters, selection, actions, analysis } = model;
  const isEdit = mode === 'edit';
  // The comments context is mounted for whoever has comments here: editors,
  // viewers where the instance lets them comment, and guests who could by
  // signing in. Without it the dashboard has no comments to describe.
  const commentsControl = useCommentsControl();
  const commentsRole: CommentsRole | null = !commentsControl
    ? null
    : !commentsControl.canComment
      ? 'guest'
      : commentsControl.canModerate
        ? 'moderator'
        : 'commenter';
  // The viewer cannot list versions, so its signal is the role: history and
  // restore belong to whoever can edit.
  const showVersions = (canEdit ?? isEdit) && model.versions.saved;
  const foldableNames = sections.foldable.map((s) => s.name);
  const pinnedNames = sections.pinned.map((s) => s.name);
  const persistentFilters = filters.persistent.map((s) => s.name);
  const ownSelection = selection.filter((s) => !s.floating);

  const parts: (PartProps & { navLabel: string })[] = [];

  // 1. Tabs
  parts.push({
    id: 'tabs',
    navLabel: 'Tabs',
    icon: 'mdi:tab',
    title: 'Move between tabs',
    subtitle:
      tabs.count > 1
        ? `${plural(tabs.count, 'tab')}${
            tabs.groupNames.length ? `, in ${plural(tabs.groupNames.length, 'group')}` : ''
          }, listed in the sidebar`
        : 'This dashboard is a single tab',
    points: [
      <>
        The sidebar lists every tab; the one you are on is filled in. The{' '}
        <Kbd icon="mdi:menu">menu button</Kbd> at the left of the header folds it away and brings
        it back.
      </>,
      tabs.groupNames.length > 0 && (
        <>
          Tabs are gathered under headings: {listNames(tabs.groupNames, 5)}. A heading only labels
          the tabs under it.
        </>
      ),
      <>
        Every tab is a link: middle-click or Ctrl/⌘-click one to open it in a new browser tab, and
        bookmark or share its address.
      </>,
    ],
    demoLabel: tabs.count > 1 ? 'The tabs · click one to open it' : 'The tab',
    demo: <TabPillsDemo model={model} mode={mode} onCurrent={onClose} />,
    showMe: { target: 'tabs', label: 'Show me the tab you are on' },
  });

  // 2. Reading a tab
  const sectionsSource = sources.sections;
  const foldableHere = foldableNames.length > 0;
  const headingsOnly = !foldableHere && sections.headings > 0;
  const demoSections = sectionsSource?.sections.length ?? 2;
  parts.push({
    id: 'reading',
    navLabel: 'Sections',
    icon: 'mdi:view-agenda-outline',
    title: 'Read a tab',
    subtitle: foldableHere
      ? `${plural(foldableNames.length, 'section')} on ${tabName} fold and unfold`
      : 'A grid of components, gathered into sections that fold',
    points: [
      <>
        A tab is a grid of components: figures, tables, cards and text, often gathered into
        sections. Click a section's header to fold it; folded, it keeps showing its key numbers.
      </>,
      foldableHere && <>On {tabName}: {listNames(foldableNames, 5)}.</>,
      (foldableNames.length > 1 || (!foldableHere && demoSections > 1)) && (
        <>
          <Kbd icon="mdi:unfold-more-horizontal">Expand all</Kbd> /{' '}
          <Kbd icon="mdi:unfold-less-horizontal">Collapse all</Kbd>, above the sections, opens or
          folds every one at once.
        </>
      ),
      pinnedNames.length > 0 && (
        <>
          Sections marked <Kbd icon="mdi:pin">with a pin</Kbd> ({listNames(pinnedNames)}) are on
          every tab of the dashboard.
        </>
      ),
      <>
        Page width and text size are your own: <Kbd>Settings → Your view</Kbd>. They are kept in
        this browser and change nothing for anyone else.
      </>,
    ],
    demoLabel:
      sectionsSource === null
        ? 'An example · fold a section'
        : sectionsSource?.scope === 'pinned'
          ? `Live · a pinned section, from ${sectionsSource.tabLabel}`
          : sectionsSource?.scope === 'sibling'
            ? `Live · from ${sectionsSource.tabLabel} · fold a section`
            : `Live · ${tabName}'s own · fold a section`,
    demo: <SectionsDemo source={sectionsSource} />,
    note: headingsOnly && (
      <Note testId="guide-headings-note">
        On {tabName}, sections are headings only: they name the parts of the tab and do not fold.
      </Note>
    ),
    showMe: { target: 'sections', label: 'Show me where to fold' },
    footer: (
      <Button
        variant="default"
        size="xs"
        leftSection={<Icon icon="mdi:monitor-eye" width={14} />}
        onClick={onOpenYourView}
        data-testid="guide-open-your-view"
      >
        Open Your view
      </Button>
    ),
  });

  // 3. Filters
  const selectionPlaces = [
    ...ownSelection.map((s) => s.title),
    ...(model.mapPanel ? ['the map panel'] : []),
  ];
  // What a selection is made with depends on what can take one here.
  const selectsPoints = model.mapPanel || ownSelection.some((s) => s.kind !== 'table');
  const selectsRows = ownSelection.some((s) => s.kind === 'table');
  const selectionSubject =
    selectsPoints && selectsRows ? 'Figures, maps and tables' : selectsRows ? 'Tables' : 'Figures and maps';
  const selectionHow = [
    selectsPoints && 'draw a lasso or box, or click a point',
    selectsRows && 'select rows',
  ]
    .filter(Boolean)
    .join(', or ');
  const acrossTabs = (() => {
    const kept = persistentFilters.length
      ? `${listNames(persistentFilters)} ${persistentFilters.length === 1 ? 'keeps its' : 'keep their'} values`
      : '';
    const map = model.mapPanel ? 'the map panel keeps its selection' : '';
    const rest = 'the other filters belong to their tab';
    if (kept && map) return `Switching tabs: ${kept}, ${map}; ${rest}.`;
    if (kept) return `Switching tabs: ${kept}; ${rest}.`;
    if (map) return `Switching tabs: ${map}; ${rest}.`;
    return tabs.count > 1 && filters.total > 0
      ? "Filters belong to their tab: switching tabs starts from that tab's own."
      : '';
  })();
  const filterSource = sources.filter;
  parts.push({
    id: 'filters',
    navLabel: 'Filters',
    icon: 'mdi:filter-variant',
    title: 'Filter the data',
    subtitle:
      filters.total > 0
        ? `${plural(filters.total, 'filter')} on this tab${
            filters.sections.length ? `, in ${plural(filters.sections.length, 'section')}` : ''
          }`
        : selection.length > 0
          ? 'Select on a figure or the map to filter the rest'
          : 'This tab has no filters',
    points: [
      filters.total > 0 && (
        <>
          The filter panel, left of the tab (on a phone,{' '}
          <Kbd icon="mdi:filter-variant">Filters</Kbd> in the header), holds the tab's filters. Pick
          values and every component on the same data follows.
        </>
      ),
      acrossTabs,
      selectionPlaces.length > 0 && (
        <>
          {selectionSubject} filter too: {selectionHow}. Here: {listNames(selectionPlaces, 3)}.
        </>
      ),
      (filters.total > 0 || selectionPlaces.length > 0) && (
        <>
          While anything is filtered, pinned sections say{' '}
          <Badge size="xs" variant="light" component="span">
            Filtered
          </Badge>{' '}
          and read <Text span inherit fw={600}>n / N</Text>;{' '}
          <Kbd icon="bx:reset" color="orange">
            Reset
          </Kbd>
          , orange in the panel's header, clears it all.
        </>
      ),
    ],
    demoLabel: 'Live · pick a value',
    demo:
      filterSource === undefined ? (
        <LiveFilterDemoSkeleton />
      ) : filterSource ? (
        <LiveFilterDemo source={filterSource} />
      ) : undefined,
    showMe: { target: 'filters', label: 'Show me the filter' },
  });

  // 4. Component actions
  parts.push({
    id: 'components',
    navLabel: 'Components',
    icon: 'mdi:cursor-default-click-outline',
    title: "Use a component's actions",
    subtitle: 'Hover a component: its actions show in its top-right corner',
    points: [
      <>
        Each icon has a tooltip; a card keeps its row along its bottom edge.{' '}
        <Kbd icon="bx:reset" color="orange">
          Reset selection
        </Kbd>{' '}
        stays on screen, filled, while that component's selection filters the tab.
      </>,
      <>
        Pick a kind: the tile is one of this dashboard's own, live, and every icon on it works.
        Point at a line of the lists to find its icon on the tile.
      </>,
      isEdit && (
        <>
          In the editor every tile also has a grip to move it, a corner to resize it and a{' '}
          <Kbd icon="tabler:dots-vertical">menu</Kbd>.
        </>
      ),
    ],
    demoLabel: isEdit ? 'Live · try its icons and the ⋮ menu' : 'Live · try its icons',
    demo: <ActionsDemo model={model} family={sources.family} mode={mode} />,
    showMe: { target: 'actions', label: 'Show me the actions' },
  });

  // 5. Analysis — only where the header offers it.
  if (analysis.available) {
    parts.push({
      id: 'analysis',
      navLabel: 'Analysis',
      icon: 'mdi:select-group',
      title: 'Compare groups with Analysis',
      subtitle: 'Save selections as groups, then compare them on the figures and cards',
      points: [
        <>
          <Kbd icon="mdi:select-group">Analysis</Kbd> in the header turns the mode on and opens its
          panel; the tiles a selection can be made on get a dashed outline.
        </>,
        <>
          Select points or rows, save them as a group, then colour or split the figures by group
          and read each card group by group. Try it below.
        </>,
      ],
      demoLabel: 'Live · three steps',
      demo: <AnalysisDemo source={sources.analysis} />,
      showMe: { target: 'analysis', label: 'Show me the next step' },
    });
  }

  // 5b. The genome browser: only where the dashboard has one, on any tab.
  // The Guide carries what is true of every genome browser tile; why this
  // dashboard has one where it does is the author's line in the section that
  // holds it, shown as written under "Where the browser appears".
  if (sources.genome) {
    const genome = sources.genome;
    const genomeConfig = genomeConfigOf(genome.tile.metadata);
    const tilesHere = genome.tabs.some((t) => t.here);
    // What the tile adds on top of the shared gestures, from its own config:
    // the stepper needs `locus_from`, the Breakpoint view a mate, the circular
    // view a `views` entry.
    const genomeMeta = genome.tile.metadata;
    const genomeViews: unknown[] = Array.isArray(genomeMeta.views) ? genomeMeta.views : [];
    const genomeStepper = Boolean(genomeConfig.locusFromDc) && genomeMeta.call_stepper !== false;
    const genomeBreakpoint = genomeViews.includes('breakpoint');
    const genomeCircular = genomeViews.includes('circular');
    parts.push({
      id: 'genome',
      navLabel: 'Genome',
      icon: 'mdi:dna',
      title: 'Browse the genome',
      subtitle: tilesHere
        ? 'A genome browser on this tab shows the tracks behind the numbers'
        : `A genome browser on ${genome.tile.tabLabel} shows the tracks behind the numbers`,
      points: [
        <>
          The browser has JBrowse's own menus. <Kbd icon="mdi:format-list-checks">Tracks</Kbd>{' '}
          lists every track: search it, then switch a track on to open it or off to close it. The
          settings icon switches the header, the overview ruler and the status bar, and loads
          tracks the region is too large for.
        </>,
        <>
          Drag to move along the genome. Hold Ctrl or ⌘ and turn the mouse wheel, or pinch on a
          trackpad, to zoom. A plain wheel scrolls the page, not the tracks.
        </>,
        genomeConfig.locusFromDc && (
          <>
            The browser follows the rows you filter in{' '}
            <Text span inherit fw={600}>
              {genomeConfig.locusFromDc}
            </Text>
            : when a few rows are left, it jumps to where they sit on the genome. With many rows
            left, it stays where it is.
          </>
        ),
        genomeStepper && (
          <>
            Without a pick, the browser opens on the first call. The{' '}
            <Kbd icon="mdi:chevron-right">previous and next</Kbd> buttons of the header jump to the
            nearest region left or right of the view (overlapping regions of several samples are one
            stop); the region count opens a sortable, searchable list, and the density strip under
            the header shows where the regions fall. The view moves, the filters do not. Type a gene
            name in the locus box to go to it.
          </>
        ),
        <>
          The browser sits on one tab. The genomic plots on the other tabs carry an{' '}
          <Kbd icon="mdi:dna">Open in genome browser</Kbd> action: it opens that tab on the point
          you clicked, the region you selected or the window in view.
        </>,
        <>
          Where a tab has a genome navigator above the browser, drag across it to pick a region.
          The browser follows that region without filtering anything itself.
        </>,
        genomeBreakpoint && (
          <>
            <Kbd icon="mdi:vector-link">Breakpoint view</Kbd>, in the tile's toolbar, opens both
            sides of the call in two panes joined by the reads that span them.
          </>
        ),
        genomeCircular && (
          <>
            <Kbd icon="mdi:chart-donut">Circular view</Kbd>, in the tile's toolbar, draws the
            structural variants of the run as chords around the genome.
          </>
        ),
        genomeConfig.selects && (
          <>
            {genomeConfig.selectionMode === 'visible_tracks'
              ? 'The tracks open in the view select their samples'
              : 'Click a track, or a feature on it, to select its sample'}
            {genomeConfig.selectionColumn ? (
              <>
                {' '}
                on{' '}
                <Text span inherit fw={600}>
                  {genomeConfig.selectionColumn}
                </Text>
              </>
            ) : null}
            : the rest of the tab filters to it.
          </>
        ),
        genomeConfig.ucscTracks.length > 0 && (
          <>
            {plural(genomeConfig.ucscTracks.length, 'track')} here come from the UCSC Genome
            Browser, for the same assembly. They are in the Tracks menu with the others.
          </>
        ),
        <>
          <Kbd icon="mdi:information-outline">Component metadata</Kbd>, in the tile's corner, lists
          every track with where it comes from.
        </>,
      ],
      demoLabel: genome.tile.here
        ? 'This tab · the genome browser'
        : `From ${genome.tile.tabLabel} · the genome browser`,
      demo: <GenomeDemo source={genome} />,
      note: <GenomeWhere tabs={genome.tabs} mode={mode} onCurrent={onClose} />,
      showMe: { target: 'genome', label: 'Show me the browser' },
    });
  }

  // 6. Comments and annotations: only where the dashboard has comments.
  if (commentsRole) {
    const guest = commentsRole === 'guest';
    const moderator = commentsRole === 'moderator';
    parts.push({
      id: 'comments',
      navLabel: 'Comments',
      icon: 'mdi:comment-text-multiple-outline',
      title: 'Comment and annotate',
      subtitle: 'Talk about a figure where it is, or about the whole tab',
      points: guest
        ? [
            <>
              <Kbd icon="mdi:comment-plus-outline">Comments</Kbd> in a component's corner opens a
              thread on it; in the header it opens every thread of the tab. To write on the
              dashboard, sign in first: the icon asks you to.
            </>,
            <>
              An annotation is a note drawn on a chart, over a range or a group of points. The ones
              an editor has published are visible to you on the chart.
            </>,
          ]
        : [
            <>
              <Kbd icon="mdi:comment-plus-outline">Comments</Kbd> in a component's corner opens a
              thread on it; in the header it opens every thread of the tab. A thread stays open
              until it is resolved. A comment keeps the filters and the selection it was written
              with, and clicking the thread brings them back.
            </>,
            moderator ? (
              <>
                <Kbd icon="mdi:draw">Annotate</Kbd>, on a figure that supports it, draws a range, a
                line, a note or a group of points on the chart. It stays with editors until you
                switch on Visible to viewers.
              </>
            ) : (
              <>
                An annotation is a note drawn on a chart. The ones an editor has published are
                drawn on the chart for everyone; resolving a thread is for editors.
              </>
            ),
          ],
      demoLabel: 'An example · click the comments icon, then reply',
      demo: <CommentsDemo role={commentsRole} family={sources.family} />,
      showMe: { target: 'comments', label: 'Show me the comments button' },
    });
  }

  // 7. Versions: whoever opens the Guide learns the dashboard keeps its history.
  if (model.versions.saved) {
    parts.push({
      id: 'versions',
      navLabel: 'Versions',
      icon: 'mdi:history',
      title: 'Go back to an earlier version',
      subtitle: 'Every save is kept: for one component or for the whole dashboard',
      points: [
        <>
          Every save records the whole dashboard: its layout, its components and the version of
          each data collection it showed. Autosaves made close together fold into one version.
        </>,
        showVersions ? (
          <>
            A component keeps its id from save to save, so it has a history of its own:{' '}
            <Kbd icon="mdi:history">History</Kbd> in its menu{isEdit ? '' : ', in the editor,'}{' '}
            lists its versions, newest first. Preview one, read only, compare two, or restore just
            that component.
          </>
        ) : (
          <>
            The dashboard's editors can look back at a single component, preview an earlier
            version of it read only, compare two, or restore just that component.
          </>
        ),
        showVersions ? (
          <>
            The same works for the whole dashboard:{' '}
            <Kbd icon="ic:baseline-settings">Settings → History</Kbd>
            {isEdit ? '' : ', in the editor,'} lists every version. Preview opens one in a new tab,
            read only; Restore brings the dashboard back to it, after a confirmation; a bookmark
            names a version and keeps it from being pruned. Deleting a version is for the owner.
          </>
        ) : (
          <>
            The same goes for the whole dashboard. A link to a version opens it for you, read
            only, with nothing to change.
          </>
        ),
        <>
          A preview is this same page drawn from a past version. A bar at the top says which one,
          and whether each data collection is on that version's data or on its latest.
        </>,
        ...(showVersions
          ? [
              <>
                {isEdit ? '' : 'In the editor, '}
                <Kbd icon="ic:baseline-settings">Settings → Data version</Kbd> looks at the
                dashboard as of a version, or puts one data collection back on an earlier version
                of its data. It is only a view: nothing is saved, and it is gone on reload.
              </>,
            ]
          : []),
      ],
      demoLabel: 'An example · one component, its history',
      demo: <VersionsDemo family={sources.family} />,
      ...(showVersions ? { showMe: { target: 'versions', label: 'Show me Preview' } } : {}),
    });
  }

  // 8. Your settings
  parts.push({
    id: 'settings',
    navLabel: 'Settings',
    icon: 'mdi:tune-variant',
    title: 'Make it yours',
    subtitle: 'Your view: only for you, kept in this browser',
    points: [
      <>
        <Kbd icon="ic:baseline-settings">Settings</Kbd> in the header, under Your view: the text
        size of figures, tables and cards, and the page width.
      </>,
      <>The sun / moon at the foot of the sidebar switches between light and dark.</>,
      <>Settings also says what the dashboard is: its project, its run and who owns it.</>,
    ],
    demoLabel: 'Width, text size, light or dark',
    demo: <YourViewDemo />,
    showMe: { target: 'settings', label: 'Show me what they do' },
    footer: (
      <Button
        variant="default"
        size="xs"
        leftSection={<Icon icon="mdi:monitor-eye" width={14} />}
        onClick={onOpenYourView}
      >
        Open Your view
      </Button>
    ),
  });

  return (
    <div
      ref={layerRef}
      className="depictio-guide-layer"
      role="region"
      aria-labelledby="guide-heading"
      data-testid="dashboard-guide"
      style={
        canvasBox
          ? {
              top: canvasBox.top,
              left: canvasBox.left,
              width: canvasBox.width,
              height: canvasBox.height,
              right: 'auto',
              bottom: 'auto',
              transition: 'none',
            }
          : undefined
      }
    >
      <Container size={900} px={{ base: 'md', sm: 'xl' }} py={{ base: 'lg', sm: 'xl' }}>
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start" wrap="nowrap" gap="md">
            <Group gap="md" wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
              <ThemeIcon size={48} radius="md" variant="light" style={{ flexShrink: 0 }}>
                <Icon icon="mdi:help-circle-outline" width={28} height={28} />
              </ThemeIcon>
              <Box style={{ minWidth: 0 }}>
                <Text size="xs" c="dimmed" tt="uppercase" fw={700} truncate style={{ letterSpacing: '0.06em' }}>
                  {dashboardName}
                </Text>
                <Title
                  order={1}
                  size="h2"
                  id="guide-heading"
                  ref={headingRef}
                  tabIndex={-1}
                  style={{ outline: 'none' }}
                  lh={1.2}
                >
                  Guide
                </Title>
                <Text c="dimmed" size="sm" lh={1.45}>
                  How to move around this dashboard, filter it and read its components
                </Text>
              </Box>
            </Group>
            <Button
              variant="default"
              size="xs"
              leftSection={<Icon icon="mdi:arrow-left" width={14} />}
              onClick={onClose}
              visibleFrom="sm"
              style={{ flexShrink: 0 }}
              data-testid="guide-close"
            >
              Back to {tabName}
            </Button>
            <ActionIcon
              variant="default"
              size="lg"
              onClick={onClose}
              hiddenFrom="sm"
              aria-label={`Back to ${tabName}`}
              style={{ flexShrink: 0 }}
            >
              <Icon icon="mdi:close" width={18} />
            </ActionIcon>
          </Group>

          {intro && (
            <Paper
              withBorder
              radius="lg"
              p={{ base: 'md', sm: 'lg' }}
              style={{ borderLeft: '3px solid var(--mantine-primary-color-filled)' }}
              data-testid="guide-intro"
            >
              <TextRenderer metadata={introMetadata} />
            </Paper>
          )}

          <Group gap={6} wrap="wrap" component="nav" aria-label="Guide parts">
            {parts.map((p) => (
              <Button
                key={p.id}
                component="a"
                href={`#guide-${p.id}`}
                variant="subtle"
                color="gray"
                size="compact-sm"
                leftSection={<Icon icon={p.icon} width={14} />}
                onClick={(e: React.MouseEvent) => {
                  e.preventDefault();
                  layerRef.current
                    ?.querySelector(`#guide-${p.id}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
              >
                {p.navLabel}
              </Button>
            ))}
          </Group>

          {parts.map(({ navLabel: _navLabel, ...p }) => (
            <GuidePart key={p.id} {...p} />
          ))}

          <Group justify="center" py="md">
            <Button
              variant="light"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
              onClick={onClose}
              data-testid="guide-close-bottom"
            >
              Back to {tabName}
            </Button>
          </Group>
          <Group justify="center" gap="xs" pb="md" wrap="wrap">
            <Text size="xs" c="dimmed" ta="center">
              The Guide is always one click away:{' '}
              <Text span inherit fw={600}>
                Guide
              </Text>{' '}
              at the end of the tab list, or{' '}
              <Icon icon="mdi:help-circle-outline" width={13} style={{ verticalAlign: '-2px' }} />{' '}
              in the header.
            </Text>
          </Group>
        </Stack>
      </Container>
    </div>
  );
};

export default DashboardGuide;

/**
 * The dashboard Guide: one page on how to move around a dashboard, filter it
 * and read its components, that a reader can open at any time.
 *
 * Not a tour. There are no steps and nothing to dismiss: the page is a column
 * of parts, each a short explanation, a small working demo, and a "Show me"
 * that rings the real control. The explanations are generic; what fills them —
 * the tabs, the sections, the filters, the actions — is read from the tab the
 * Guide was opened on (`buildGuideModel`), and the demos are built from the
 * dashboard's own components (`useGuideSources`), so the Guide never describes
 * a control the dashboard does not have.
 *
 * The page covers the tab's canvas only. The sidebar, the header and the
 * filter panel stay beside it, so "Show me" on one of those rings it with the
 * Guide still open; only what is in the canvas closes the Guide first.
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
import { TextRenderer } from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  GuideModel,
  PersistentSection,
  StoredMetadata,
} from 'depictio-react-core';

import { AnalysisDemo, DemoFrame, TabPillsDemo, YourViewDemo } from './GuideDemos';
import { ActionsDemo } from './demos/ActionsDemo';
import { LiveFilterDemo, LiveFilterDemoSkeleton } from './demos/LiveFilterDemo';
import { SectionsDemo } from './demos/SectionsDemo';
import { CANVAS_SELECTOR, findGuideTarget, type GuideTarget } from './showMe';
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
  onClose: () => void;
  onShowMe: (target: GuideTarget) => void;
  /** Opens the dashboard settings on "Your view". */
  onOpenYourView: () => void;
  /** Components a selection can be made on, for the selection "Show me". */
  selectionIds: readonly string[];
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
// "Show me" availability
// ---------------------------------------------------------------------------

const TARGETS: GuideTarget[] = [
  'tabs',
  'sections',
  'filters',
  'selection',
  'pinned',
  'actions',
  'analysis',
  'settings',
  'guide',
];

/**
 * Which "Show me" targets the page has right now. Polled while the Guide is
 * up: tiles and the filter panel mount as their data arrives, and a "Show me"
 * offered for an element that is not there would ring nothing.
 */
function useTargetAvailability(selectionIds: readonly string[]): Record<GuideTarget, boolean> {
  const ids = useRef(selectionIds);
  ids.current = selectionIds;
  const read = () =>
    Object.fromEntries(
      TARGETS.map((t) => [t, findGuideTarget(t, { selectionIds: ids.current }) !== null]),
    ) as Record<GuideTarget, boolean>;
  const [available, setAvailable] = useState(read);
  useEffect(() => {
    const tick = () =>
      setAvailable((prev) => {
        const next = read();
        return TARGETS.every((t) => prev[t] === next[t]) ? prev : next;
      });
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
    // `read` only reads refs and the DOM.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return available;
}

// ---------------------------------------------------------------------------
// The layer's place: over the canvas, and only the canvas
// ---------------------------------------------------------------------------

type LayerBox = { top: number; left: number; width: number; height: number };

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
  /** Said in the footer when the page has nothing to point at; nothing when absent. */
  absent?: string;
}

/** The part's main action: rings the real thing the part is about. */
const ShowMeButton: React.FC<{
  spec: ShowMeSpec;
  onShowMe: (target: GuideTarget) => void;
  size?: 'sm' | 'xs';
}> = ({ spec, onShowMe, size = 'sm' }) => (
  <Button
    variant="light"
    size={size}
    radius="md"
    leftSection={<Icon icon="mdi:crosshairs-gps" width={size === 'sm' ? 18 : 15} />}
    onClick={() => onShowMe(spec.target)}
    data-testid={`guide-show-${spec.target}`}
    style={{ flexShrink: 0 }}
  >
    {spec.label}
  </Button>
);

const Absent: React.FC<{ target: GuideTarget; children: React.ReactNode }> = ({
  target,
  children,
}) => (
  <Group gap={6} wrap="nowrap" data-testid={`guide-absent-${target}`}>
    <Icon
      icon="mdi:eye-off-outline"
      width={14}
      style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }}
    />
    <Text size="xs" c="dimmed">
      {children}
    </Text>
  </Group>
);

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
  /** The part's "Show me", in its header. */
  showMe?: ShowMeSpec;
  /** Secondary actions, under the demo. */
  footer?: React.ReactNode;
}

/** One part of the Guide: what it is about, a few lines, a demo, Show me. */
const GuidePart: React.FC<
  PartProps & {
    available: Record<GuideTarget, boolean>;
    onShowMe: (target: GuideTarget) => void;
  }
> = ({ id, icon, title, subtitle, points, demo, demoLabel, note, showMe, footer, available, onShowMe }) => {
  const showMeHere = showMe && available[showMe.target];
  const absent = showMe && !showMeHere && showMe.absent;
  const shownPoints = points.filter(Boolean);
  return (
    <Paper
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
          {showMeHere && <ShowMeButton spec={showMe} onShowMe={onShowMe} />}
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
        {(footer || absent) && (
          <Group gap="sm" wrap="wrap">
            {footer}
            {absent && showMe && <Absent target={showMe.target}>{absent}</Absent>}
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
          color: color ? `var(--mantine-color-${color}-filled)` : 'var(--mantine-primary-color-filled)',
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
  onClose,
  onShowMe,
  onOpenYourView,
  selectionIds,
}) => {
  const available = useTargetAvailability(selectionIds);
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
    showMe: { target: 'tabs', label: 'Show me the tabs', absent: 'The sidebar is not on this page.' },
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
          ? 'A pinned section · fold it'
          : sectionsSource?.scope === 'sibling'
            ? `From ${sectionsSource.tabLabel} · fold a section`
            : 'Fold a section',
    demo: <SectionsDemo source={sectionsSource} />,
    note: headingsOnly && (
      <Note testId="guide-headings-note">
        On {tabName}, sections are headings only: they name the parts of the tab and do not fold.
      </Note>
    ),
    showMe: { target: 'sections', label: headingsOnly ? 'Show me the headings' : 'Show me a section' },
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
    showMe: { target: 'filters', label: 'Show me the filters', absent: 'This tab has no filter panel.' },
    footer: (available.selection && selectionPlaces.length > 0) || available.pinned ? (
      <>
        {selectionPlaces.length > 0 && available.selection && (
          <ShowMeButton
            spec={{ target: 'selection', label: 'Where to select' }}
            onShowMe={onShowMe}
            size="xs"
          />
        )}
        {available.pinned && (
          <ShowMeButton
            spec={{ target: 'pinned', label: 'A pinned section' }}
            onShowMe={onShowMe}
            size="xs"
          />
        )}
      </>
    ) : undefined,
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
      <>Pick a kind of component: the tile shows its row, the lists say what each icon does.</>,
      isEdit && (
        <>
          In the editor every tile also has a grip to move it, a corner to resize it and a{' '}
          <Kbd icon="tabler:dots-vertical">menu</Kbd>.
        </>
      ),
    ],
    demoLabel: isEdit ? 'Hover the icons · open the ⋮ menu' : 'Hover the icons',
    demo: <ActionsDemo model={model} components={components} mode={mode} />,
    showMe: {
      target: 'actions',
      label: 'Show me on a component',
      absent: actions.length > 0 ? undefined : 'No component on this tab has actions.',
    },
  });

  // 5. Analysis — only where the header offers it.
  if (analysis.available) {
    parts.push({
      id: 'analysis',
      navLabel: 'Analysis',
      icon: 'mdi:select-group',
      title: 'Compare groups with Analysis',
      subtitle: 'Save selections as groups, colour or split every figure, compare groups',
      points: [
        <>
          <Kbd icon="mdi:select-group">Analysis</Kbd> in the header turns the mode on and opens its
          panel. The tiles you can select on get a dashed outline.
        </>,
        analysis.selectable > 0 ? (
          <>
            Select some points on one of them ({plural(analysis.selectable, 'tile')} on this tab),
            then save the selection as a group.
          </>
        ) : (
          <>No tile on this tab takes a selection; groups saved on another tab still apply here.</>
        ),
        <>
          With groups saved, colour or split every figure by them, and read each card's numbers
          group by group.
        </>,
      ],
      demoLabel: 'Turn it on',
      demo: <AnalysisDemo />,
      showMe: {
        target: 'analysis',
        label: 'Show me Analysis',
        absent: 'The Analysis button is off screen at this width.',
      },
    });
  }

  // 6. Your settings
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
    demoLabel: 'Width and text size',
    demo: <YourViewDemo />,
    showMe: {
      target: 'settings',
      label: 'Show me Settings',
      absent: 'Settings is off screen at this width.',
    },
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
            <GuidePart key={p.id} {...p} available={available} onShowMe={onShowMe} />
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
            {available.guide && (
              <ShowMeButton
                spec={{ target: 'guide', label: 'Show me' }}
                onShowMe={onShowMe}
                size="xs"
              />
            )}
          </Group>
        </Stack>
      </Container>
    </div>
  );
};

export default DashboardGuide;

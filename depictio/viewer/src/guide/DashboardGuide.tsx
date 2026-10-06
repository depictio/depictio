/**
 * The dashboard Guide: one page on how to move around a dashboard, filter it
 * and read its components, that a reader can open at any time.
 *
 * Not a tour. There are no steps and nothing to dismiss: the page is a column
 * of parts, each a short explanation, a small working demo, and a "Show me"
 * that closes the Guide and rings the real control on the tab for a moment.
 * The explanations are generic; what fills them — the tabs, the sections, the
 * filters, the actions — is read from the tab the Guide was opened on
 * (`buildGuideModel`), so the Guide never describes a control the dashboard
 * does not have.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
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
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { SectionIcon, TextRenderer } from 'depictio-react-core';
import type { GuideFilterSection, GuideModel, StoredMetadata } from 'depictio-react-core';

import {
  ActionsDemo,
  AnalysisDemo,
  DemoFrame,
  FilterDemo,
  SectionsDemo,
  TabPillsDemo,
  YourViewDemo,
} from './GuideDemos';
import { findGuideTarget, type GuideTarget } from './showMe';

export interface DashboardGuideProps {
  model: GuideModel;
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
// Pieces
// ---------------------------------------------------------------------------

const ShowMe: React.FC<{
  target: GuideTarget;
  available: boolean;
  onShowMe: (target: GuideTarget) => void;
  label?: string;
  /** Said instead of the button when the tab has nothing to point at. */
  absent: string;
}> = ({ target, available, onShowMe, label = 'Show me', absent }) =>
  available ? (
    <Button
      variant="light"
      size="xs"
      leftSection={<Icon icon="mdi:target" width={14} />}
      onClick={() => onShowMe(target)}
      data-testid={`guide-show-${target}`}
    >
      {label}
    </Button>
  ) : (
    <Group gap={6} wrap="nowrap" data-testid={`guide-absent-${target}`}>
      <Icon
        icon="mdi:eye-off-outline"
        width={14}
        style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }}
      />
      <Text size="xs" c="dimmed">
        {absent}
      </Text>
    </Group>
  );

interface PartProps {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  points: React.ReactNode[];
  /** Below the points: a legend the points introduce. */
  extra?: React.ReactNode;
  demo?: React.ReactNode;
  demoLabel?: string;
  footer: React.ReactNode;
}

/** One part of the Guide: what it is about, a few lines, a demo, Show me. */
const GuidePart: React.FC<PartProps> = ({
  id,
  icon,
  title,
  subtitle,
  points,
  extra,
  demo,
  demoLabel,
  footer,
}) => (
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
      <Group gap="md" wrap="nowrap" align="flex-start">
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
        {points.filter(Boolean).map((p, i) => (
          <List.Item key={i}>{p}</List.Item>
        ))}
      </List>
      {extra}
      {demo && <DemoFrame label={demoLabel}>{demo}</DemoFrame>}
      <Group gap="sm" wrap="wrap">
        {footer}
      </Group>
    </Stack>
  </Paper>
);

/** The filter panel's sections, named and iconed as the panel draws them. */
const FilterSectionList: React.FC<{ sections: GuideFilterSection[] }> = ({ sections }) => (
  <Stack gap={6} mt={8} data-testid="guide-filter-sections">
    {sections.map((s) => (
      <Group key={s.name} gap="sm" wrap="nowrap">
        <SectionIcon spec={s.spec ?? { name: s.name }} size={18} />
        <Text size="sm" fw={500} truncate style={{ minWidth: 0 }}>
          {s.name}
        </Text>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {plural(s.controls, 'filter')}
        </Text>
        {s.persistent && (
          <Tooltip label="Its values stay set when you switch tabs" withArrow>
            <Badge
              size="xs"
              variant="light"
              color="gray"
              leftSection={<Icon icon="mdi:pin" width={10} />}
              style={{ flexShrink: 0 }}
            >
              Every tab
            </Badge>
          </Tooltip>
        )}
      </Group>
    ))}
  </Stack>
);

/** An inline mention of a control, drawn as the control's own icon. */
const Kbd: React.FC<{ icon?: string; children: React.ReactNode }> = ({ icon, children }) => (
  <Text span inherit fw={600} style={{ whiteSpace: 'nowrap' }}>
    {icon && (
      <Icon
        icon={icon}
        width={14}
        style={{ verticalAlign: '-2px', marginRight: 3, color: 'var(--mantine-primary-color-filled)' }}
      />
    )}
    {children}
  </Text>
);

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

const DashboardGuide: React.FC<DashboardGuideProps> = ({
  model,
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

  const { tabs, sections, filters, selection, actions, editActions, analysis } = model;
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
    footer: (
      <ShowMe
        target="tabs"
        available={available.tabs}
        onShowMe={onShowMe}
        label="Show me the tabs"
        absent="The sidebar is not on this page."
      />
    ),
  });

  // 2. Reading a tab
  parts.push({
    id: 'reading',
    navLabel: 'Sections',
    icon: 'mdi:view-agenda-outline',
    title: 'Read a tab',
    subtitle:
      foldableNames.length > 0
        ? `${plural(foldableNames.length, 'section')} on ${tabName} fold and unfold`
        : 'Components in a grid, at the width and size that suit you',
    points: [
      <>
        A tab is a grid of components: figures, tables, cards and text, often gathered into
        sections. Click a section's header to fold it; folded, it keeps showing its key numbers.
      </>,
      foldableNames.length > 0 && <>On {tabName}: {listNames(foldableNames, 5)}.</>,
      foldableNames.length > 1 && (
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
    demoLabel: 'Fold a section',
    demo: <SectionsDemo model={model} />,
    footer: (
      <>
        <ShowMe
          target="sections"
          available={available.sections}
          onShowMe={onShowMe}
          label="Show me a section"
          absent="This tab has no sections to fold."
        />
        <Button
          variant="default"
          size="xs"
          leftSection={<Icon icon="mdi:monitor-eye" width={14} />}
          onClick={onOpenYourView}
          data-testid="guide-open-your-view"
        >
          Open Your view
        </Button>
      </>
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
    selectsPoints && 'click a point, or draw a lasso or box around some',
    selectsRows && 'select rows in a table',
  ]
    .filter(Boolean)
    .join(', or ');
  const acrossTabs = (() => {
    const kept = persistentFilters.length
      ? `the values set in ${listNames(persistentFilters)} stay set when you switch tabs`
      : '';
    const map = model.mapPanel ? 'a selection made on the map panel' : '';
    if (kept && map) return `Across tabs: ${kept}, and so does ${map}. The other filters belong to their own tab.`;
    if (kept) return `Across tabs: ${kept}. The other filters belong to their own tab.`;
    if (map) return `Across tabs: ${map} stays when you switch tabs. The other filters belong to their own tab.`;
    return tabs.count > 1 && filters.total > 0
      ? "Filters belong to their tab: switching tabs starts from that tab's own."
      : '';
  })();
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
          The filter panel on the left holds this tab's filters; on a phone it opens from{' '}
          <Kbd icon="mdi:filter-variant">Filters</Kbd> in the header. Pick values and every
          component reading the same data follows.
          {filters.sections.length > 0 && <FilterSectionList sections={filters.sections} />}
        </>
      ),
      acrossTabs,
      selectionPlaces.length > 0 && (
        <>
          {selectionSubject} filter too: {selectionHow}, and the rest of the tab follows. Here:{' '}
          {listNames(selectionPlaces, 3)}. A tile's <Kbd icon="bx:reset">Reset selection</Kbd>{' '}
          clears its own.
        </>
      ),
      sections.fannedOut.length > 0 || pinnedNames.length > 0 ? (
        <>
          While something is filtered, a pinned section says{' '}
          <Badge size="xs" variant="light" component="span">
            Filtered
          </Badge>{' '}
          and, folded, reads its numbers as <Text span inherit fw={600}>n / N</Text>: what is left, out of
          the whole.
        </>
      ) : (
        filters.total > 0 && (
          <>
            The panel's header counts the filters that are on, and lists them so you can drop one
            at a time.
          </>
        )
      ),
      filters.total > 0 && (
        <>
          <Kbd icon="bx:reset">Reset</Kbd> in the panel's header, orange while anything is
          filtered, clears every filter on the tab.
        </>
      ),
    ],
    demoLabel: 'Pick a value',
    demo: <FilterDemo />,
    footer: (
      <>
        <ShowMe
          target="filters"
          available={available.filters}
          onShowMe={onShowMe}
          label="Show me the filters"
          absent="This tab has no filter panel."
        />
        {selectionPlaces.length > 0 && available.selection && (
          <ShowMe
            target="selection"
            available
            onShowMe={onShowMe}
            label="Where to select"
            absent=""
          />
        )}
        {available.pinned && (
          <ShowMe
            target="pinned"
            available
            onShowMe={onShowMe}
            label="A pinned section"
            absent=""
          />
        )}
      </>
    ),
  });

  // 4. Component actions
  parts.push({
    id: 'components',
    navLabel: 'Components',
    icon: 'mdi:cursor-default-click-outline',
    title: "Use a component's actions",
    subtitle:
      actions.length > 0
        ? `Hover a component: its actions show in its top-right corner`
        : 'The components on this tab carry no actions',
    points: [
      actions.length > 0 && (
        <>
          Each icon has a tooltip. Most show only while the pointer is over the component;{' '}
          <Kbd icon="bx:reset">Reset selection</Kbd> stays, in orange, while its selection filters.
        </>
      ),
      isEdit && editActions.length > 0 && (
        <>
          In the editor each tile also has <Kbd icon="mdi:dots-grid">a grip</Kbd> to move it and a{' '}
          <Kbd icon="tabler:dots-vertical">⋮</Kbd> menu:{' '}
          {listNames(
            editActions.filter((a) => a.key !== 'drag').map((a) => a.label),
            8,
          )}
          .
        </>
      ),
    ],
    extra: actions.length > 0 && (
      <Stack gap={8} data-testid="guide-action-legend">
        {actions.map((a) => (
          <Group key={a.key} gap="sm" wrap="nowrap" align="flex-start">
            <ThemeIcon
              size={26}
              radius="sm"
              variant="default"
              color={a.key === 'reset' ? 'orange' : undefined}
              style={{ flexShrink: 0 }}
            >
              <Icon
                icon={a.icon}
                width={16}
                style={
                  a.key === 'reset'
                    ? { color: 'var(--mantine-color-orange-6)' }
                    : a.key === 'group'
                      ? { color: 'var(--mantine-primary-color-filled)' }
                      : undefined
                }
              />
            </ThemeIcon>
            <Text size="sm" lh={1.45} style={{ minWidth: 0 }}>
              <Text span inherit fw={600}>
                {a.label}
              </Text>{' '}
              — {a.meaning}{' '}
              <Text span size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                {a.count === 1 ? 'On one component here' : `On ${a.count} components here`}
              </Text>
            </Text>
          </Group>
        ))}
      </Stack>
    ),
    demoLabel: isEdit ? 'Hover the icons · open the ⋮ menu' : 'Hover or pick an icon',
    demo: <ActionsDemo actions={actions} editActions={editActions} />,
    footer: (
      <ShowMe
        target="actions"
        available={available.actions}
        onShowMe={onShowMe}
        label="Show me on a component"
        absent="No component on this tab has actions."
      />
    ),
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
      footer: (
        <ShowMe
          target="analysis"
          available={available.analysis}
          onShowMe={onShowMe}
          label="Show me Analysis"
          absent="The Analysis button is off screen at this width."
        />
      ),
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
    footer: (
      <>
        <Button
          variant="light"
          size="xs"
          leftSection={<Icon icon="mdi:monitor-eye" width={14} />}
          onClick={onOpenYourView}
        >
          Open Your view
        </Button>
        <ShowMe
          target="settings"
          available={available.settings}
          onShowMe={onShowMe}
          label="Show me Settings"
          absent="Settings is off screen at this width."
        />
      </>
    ),
  });

  return (
    <div
      ref={layerRef}
      className="depictio-guide-layer"
      role="region"
      aria-labelledby="guide-heading"
      data-testid="dashboard-guide"
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
          <Text size="xs" c="dimmed" ta="center" pb="md">
            The Guide is always one click away:{' '}
            <Text span inherit fw={600}>
              Guide
            </Text>{' '}
            at the end of the tab list, or{' '}
            <Icon icon="mdi:help-circle-outline" width={13} style={{ verticalAlign: '-2px' }} /> in
            the header.
          </Text>
        </Stack>
      </Container>
    </div>
  );
};

export default DashboardGuide;

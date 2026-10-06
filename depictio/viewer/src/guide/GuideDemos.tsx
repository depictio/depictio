/**
 * The Guide's live demos: small working copies of the real controls, built
 * from the same Mantine pieces and, where the dashboard has them, its real
 * names, icons and colours. They act on themselves only — nothing here
 * filters, folds or saves anything on the dashboard.
 */
import React, { useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Badge,
  Box,
  Button,
  Chip,
  Group,
  Menu,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
  UI_SCALE_STEPS,
  useBranding,
  useGroupingColor,
  useGroupingColorVar,
} from 'depictio-react-core';
import type { FilterSectionSpec, GuideAction, GuideModel } from 'depictio-react-core';

import { resolveTabColor, resolveTabIcon, tabImageSrc } from '../chrome/Sidebar';
import { dashboardHref, dashboardLinkClickHandler } from '../dashboards/lib/dashboardLinks';
import { CONTENT_WIDTHS, type ContentWidth } from '../hooks/useContentWidthPref';

/** The inset a demo sits in, labelled so it reads as something to try. */
export const DemoFrame: React.FC<{ label?: string; children: React.ReactNode }> = ({
  label = 'Try it',
  children,
}) => (
  <Box className="depictio-guide-demo" p="md">
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb="xs" style={{ letterSpacing: '0.06em' }}>
      {label}
    </Text>
    {children}
  </Box>
);

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

/**
 * The dashboard's tabs as the sidebar draws them — same icon, colour and
 * active fill — with each tab's subtitle under its name. Each pill is the tab's
 * real link: a click opens it, a middle-click opens it in a new browser tab.
 * The current tab's pill closes the Guide instead of reloading the page.
 */
export const TabPillsDemo: React.FC<{
  model: GuideModel;
  mode: 'view' | 'edit';
  onCurrent: () => void;
}> = ({ model, mode, onCurrent }) => {
  const brand = useBranding();
  const isDark = useComputedColorScheme('light') === 'dark';
  const currentId = model.tabs.current?.id ?? null;
  return (
    <Tabs
      value={currentId}
      variant="pills"
      orientation="vertical"
      className="depictio-chrome-tabs depictio-guide-tabs"
      styles={{ root: { display: 'block' }, list: { border: 'none', width: '100%' } }}
    >
      <Tabs.List aria-label="This dashboard's tabs">
        {model.tabs.groups.map((g) => (
          <React.Fragment key={g.group ?? '__ungrouped'}>
            {g.group && (
              <Text
                className="depictio-guide-tabs-heading"
                c="dimmed"
                size="xs"
                tt="uppercase"
                fw={700}
                pl="xs"
              >
                {g.group}
              </Text>
            )}
            {g.tabs.map((t) => {
              const color = resolveTabColor(t.tab, t.isMain, brand);
              const image = tabImageSrc(t.tab, t.isMain, isDark, t.isCurrent);
              return (
                <Tabs.Tab
                  key={t.id}
                  value={t.id}
                  color={color}
                  pl="xs"
                  leftSection={
                    image ? (
                      <img
                        src={image}
                        alt=""
                        width={18}
                        height={18}
                        style={{ objectFit: 'contain', display: 'block' }}
                      />
                    ) : (
                      <Icon
                        icon={resolveTabIcon(t.tab, t.isMain)}
                        width={18}
                        height={18}
                        style={{
                          flexShrink: 0,
                          color: t.isCurrent
                            ? 'var(--mantine-color-white)'
                            : `var(--mantine-color-${color}-6)`,
                        }}
                      />
                    )
                  }
                  renderRoot={(props) => (
                    <a
                      {...props}
                      href={dashboardHref(t.id, mode)}
                      onClick={t.isCurrent ? dashboardLinkClickHandler(onCurrent) : undefined}
                    />
                  )}
                  aria-current={t.isCurrent ? 'page' : undefined}
                >
                  <span className="depictio-chrome-tab-label">{t.label}</span>
                  {t.subtitle && <span className="depictio-guide-tab-subtitle">{t.subtitle}</span>}
                </Tabs.Tab>
              );
            })}
          </React.Fragment>
        ))}
      </Tabs.List>
    </Tabs>
  );
};

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

const EXAMPLE_SECTIONS: FilterSectionSpec[] = [
  { name: 'Key numbers', icon: 'mdi:gauge', color: 'teal', description: 'The figures that matter' },
  { name: 'Details', icon: 'mdi:table', color: 'grape', description: 'The rows behind them' },
];

/**
 * Two sections in the real section chrome, folding and unfolding, with the
 * real "Collapse all / Expand all" above them. Named after this tab's own
 * sections when it has some.
 */
export const SectionsDemo: React.FC<{ model: GuideModel }> = ({ model }) => {
  const specs: FilterSectionSpec[] = (
    model.sections.foldable.length
      ? model.sections.foldable.map((s) => s.spec ?? { name: s.name })
      : EXAMPLE_SECTIONS
  ).slice(0, 2);
  const members = new Map(model.sections.foldable.map((s) => [s.name, s.members]));
  const keys = specs.map((s) => s.name);
  const [open, setOpen] = useState<string[]>(keys.slice(0, 1));
  const anyOpen = open.length > 0;
  return (
    <Stack gap={4}>
      <Group justify="flex-end">
        <Button
          variant="subtle"
          color="gray"
          size="compact-xs"
          leftSection={
            <Icon
              icon={anyOpen ? 'mdi:unfold-less-horizontal' : 'mdi:unfold-more-horizontal'}
              width={14}
            />
          }
          onClick={() => setOpen(anyOpen ? [] : keys)}
        >
          {anyOpen ? 'Collapse all' : 'Expand all'}
        </Button>
      </Group>
      <SectionAccordion value={open} onChange={setOpen}>
        {specs.map((spec) => {
          const count = members.get(spec.name) ?? 3;
          return (
            <SectionAccordionItem key={spec.name} value={spec.name} color={spec.color}>
              <Accordion.Control>
                <SectionHeader
                  spec={spec}
                  name={spec.name}
                  trailing={
                    open.includes(spec.name) ? undefined : (
                      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                        {count} component{count === 1 ? '' : 's'}
                      </Text>
                    )
                  }
                />
              </Accordion.Control>
              <Accordion.Panel>
                <SimpleGrid cols={3} spacing="xs">
                  {[0, 1, 2].map((i) => (
                    <Box key={i} className="depictio-guide-tile" h={44} />
                  ))}
                </SimpleGrid>
              </Accordion.Panel>
            </SectionAccordionItem>
          );
        })}
      </SectionAccordion>
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

const DEMO_VALUES = [
  { value: 'a', label: 'Site A', n: 3 },
  { value: 'b', label: 'Site B', n: 4 },
  { value: 'c', label: 'Site C', n: 3 },
];
const DEMO_TOTAL = DEMO_VALUES.reduce((sum, v) => sum + v.n, 0);

/**
 * A filter and what it does to the numbers: pick values and the readout drops
 * to what they leave, under the same "Filtered" badge and "n / N" a pinned
 * section shows; Reset turns orange, as the panel's does, and clears them.
 */
export const FilterDemo: React.FC = () => {
  const [picked, setPicked] = useState<string[]>([]);
  const filtered = picked.length > 0;
  const shown = filtered
    ? DEMO_VALUES.filter((v) => picked.includes(v.value)).reduce((sum, v) => sum + v.n, 0)
    : DEMO_TOTAL;
  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={600}>
          Site
        </Text>
        <Button
          leftSection={<Icon icon="bx:reset" width={12} />}
          color="orange"
          variant={filtered ? 'filled' : 'light'}
          size="compact-xs"
          disabled={!filtered}
          onClick={() => setPicked([])}
        >
          Reset
        </Button>
      </Group>
      <Chip.Group multiple value={picked} onChange={setPicked}>
        <Group gap={6}>
          {DEMO_VALUES.map((v) => (
            <Chip key={v.value} value={v.value} size="xs" variant="outline">
              {v.label}
            </Chip>
          ))}
        </Group>
      </Chip.Group>
      <Group gap="xs" wrap="nowrap" align="center" data-testid="guide-filter-readout">
        <Text size="sm" c="dimmed">
          Samples
        </Text>
        <Text size="md" fw={700} style={{ whiteSpace: 'nowrap' }}>
          {shown}
          {filtered && (
            <Text span size="sm" fw={500} c="dimmed">
              {' / '}
              {DEMO_TOTAL}
            </Text>
          )}
        </Text>
        {filtered && (
          <Badge size="xs" variant="light">
            Filtered
          </Badge>
        )}
      </Group>
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Component actions
// ---------------------------------------------------------------------------

/**
 * A tile with its action row on screen, as hovering a real one shows it: the
 * row holds the actions this tab's tiles carry, with their real icons and
 * tooltips. Picking one names it below. In the editor the row ends with the
 * tile's ⋮ menu, which opens on the real items.
 */
export const ActionsDemo: React.FC<{
  actions: GuideAction[];
  editActions: GuideAction<string>[];
}> = ({ actions, editActions }) => {
  const [picked, setPicked] = useState<GuideAction<string> | null>(null);
  const menuItems = editActions.filter((a) => a.key !== 'drag');
  const grip = editActions.find((a) => a.key === 'drag');
  return (
    <Stack gap="sm">
      {/* The row sits on a wrapper rather than inside the tile, which clips
          its contents: the ⋮ menu opens past the tile's edge. */}
      <Box pos="relative">
        <Box className="depictio-guide-tile" h={132}>
          <Box className="depictio-guide-bars" pt={44} pb={10}>
            {[46, 72, 58, 88, 64].map((h, i) => (
              <span key={i} style={{ height: `${h}%` }} />
            ))}
          </Box>
        </Box>
        <Group
          gap={4}
          wrap="nowrap"
          p={2}
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            zIndex: 1,
            borderRadius: 'var(--mantine-radius-sm)',
            background: 'var(--mantine-color-body)',
            border: '1px solid var(--mantine-color-default-border)',
          }}
        >
          {grip && (
            <Tooltip label={grip.label} withArrow>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={grip.label}
                onClick={() => setPicked(grip)}
              >
                <Icon icon={grip.icon} width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          )}
          {actions.map((a) => (
            <Tooltip key={a.key} label={a.label} withArrow>
              <ActionIcon
                variant={picked?.key === a.key ? 'light' : 'subtle'}
                color={a.key === 'reset' ? 'orange' : a.key === 'group' ? undefined : 'gray'}
                size="sm"
                aria-label={a.label}
                onClick={() => setPicked(a)}
              >
                <Icon icon={a.icon} width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          ))}
          {menuItems.length > 0 && (
            <Menu position="bottom-end" withinPortal={false} shadow="md" width={230}>
              <Menu.Target>
                <ActionIcon variant="subtle" size="sm" aria-label="Component actions">
                  <Icon icon="tabler:dots-vertical" width={16} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                {menuItems.map((a) => (
                  <Menu.Item
                    key={a.key}
                    color={a.key === 'delete' ? 'red' : undefined}
                    leftSection={<Icon icon={a.icon} width={14} />}
                    onClick={() => setPicked(a)}
                  >
                    {a.label}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
          )}
        </Group>
      </Box>
      <Text size="sm" c={picked ? undefined : 'dimmed'} mih={22} aria-live="polite">
        {picked ? (
          <>
            <Text span fw={600}>
              {picked.label}
            </Text>
            {' — '}
            {picked.meaning}
          </>
        ) : (
          'Pick an icon to see what it does.'
        )}
      </Text>
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

/**
 * The header's Analysis button and what turning it on does to the tiles: the
 * ones a selection can be made on get the dashed outline and the group marker,
 * in the same colour as the real ones.
 */
export const AnalysisDemo: React.FC = () => {
  const [on, setOn] = useState(false);
  const color = useGroupingColor();
  const colorVar = useGroupingColorVar();
  const tiles: { label: string; selectable: boolean; kind: 'dots' | 'bars' | 'value' }[] = [
    { label: 'Scatter', selectable: true, kind: 'dots' },
    { label: 'Bar chart', selectable: false, kind: 'bars' },
    { label: 'Map', selectable: true, kind: 'dots' },
  ];
  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" c="dimmed">
          In the header
        </Text>
        <Button
          size="xs"
          color={color}
          variant={on ? 'filled' : 'light'}
          leftSection={<Icon icon="mdi:select-group" width={14} height={14} />}
          onClick={() => setOn((v) => !v)}
          aria-pressed={on}
        >
          Analysis
        </Button>
      </Group>
      <SimpleGrid
        cols={3}
        spacing="xs"
        style={{ '--depictio-grouping-color': colorVar } as React.CSSProperties}
      >
        {tiles.map((t) => (
          <Box
            key={t.label}
            className={'depictio-guide-tile' + (on && t.selectable ? ' is-selectable' : '')}
            h={76}
          >
            {t.kind === 'dots' ? (
              <Box className="depictio-guide-dots" style={{ position: 'absolute', inset: 0 }}>
                {[
                  [18, 60],
                  [30, 40],
                  [44, 55],
                  [58, 30],
                  [70, 48],
                  [80, 22],
                ].map(([x, y], i) => (
                  <span key={i} style={{ left: `${x}%`, top: `${y}%` }} />
                ))}
              </Box>
            ) : (
              <Box className="depictio-guide-bars" pt={22} pb={6}>
                {[40, 70, 55].map((h, i) => (
                  <span key={i} style={{ height: `${h}%` }} />
                ))}
              </Box>
            )}
            <Text size="10px" c="dimmed" style={{ position: 'absolute', left: 8, top: 6 }}>
              {t.label}
            </Text>
            {on && t.selectable && (
              <Box style={{ position: 'absolute', right: 6, top: 4, color: colorVar }}>
                <Icon icon="mdi:select-group" width={16} height={16} />
              </Box>
            )}
          </Box>
        ))}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mih={18} aria-live="polite">
        {on
          ? 'Outlined tiles take a selection: lasso some points, then save them as a group.'
          : 'Turn it on to see which tiles take a selection.'}
      </Text>
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Your view
// ---------------------------------------------------------------------------

/** What the two "Your view" settings do, on a page in miniature. */
export const YourViewDemo: React.FC = () => {
  const [width, setWidth] = useState<ContentWidth>('full');
  const [step, setStep] = useState(UI_SCALE_STEPS.indexOf(1));
  const scale = UI_SCALE_STEPS[step];
  const share: Record<ContentWidth, number> = { full: 100, wide: 86, comfortable: 70, compact: 60 };
  return (
    <Stack gap="sm">
      <Group gap="sm" justify="space-between" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={width}
          onChange={(v) => setWidth(v as ContentWidth)}
          data={CONTENT_WIDTHS.map((w) => ({ value: w.value, label: w.label }))}
        />
        <ActionIcon.Group>
          <ActionIcon
            variant="default"
            size="input-xs"
            aria-label="Decrease font size"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            <Icon icon="mdi:format-font-size-decrease" width={14} />
          </ActionIcon>
          <Button
            variant="default"
            size="compact-xs"
            h="var(--input-height-xs)"
            style={{ pointerEvents: 'none' }}
            tabIndex={-1}
          >
            {Math.round(scale * 100)}%
          </Button>
          <ActionIcon
            variant="default"
            size="input-xs"
            aria-label="Increase font size"
            disabled={step === UI_SCALE_STEPS.length - 1}
            onClick={() => setStep((s) => Math.min(UI_SCALE_STEPS.length - 1, s + 1))}
          >
            <Icon icon="mdi:format-font-size-increase" width={14} />
          </ActionIcon>
        </ActionIcon.Group>
      </Group>
      <Box className="depictio-guide-tile" h={96} p={8}>
        <Box
          mx="auto"
          h="100%"
          style={{
            width: `${share[width]}%`,
            transition: 'width 200ms ease',
            borderInline: width === 'full' ? undefined : '1px dashed var(--mantine-color-default-border)',
            paddingInline: 8,
            overflow: 'hidden',
          }}
        >
          <Text fw={700} style={{ fontSize: 13 * scale, lineHeight: 1.3 }}>
            A tab
          </Text>
          <Text c="dimmed" style={{ fontSize: 11 * scale, lineHeight: 1.4 }}>
            Its figures, tables and cards, at the width and size you pick.
          </Text>
        </Box>
      </Box>
    </Stack>
  );
};

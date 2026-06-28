/**
 * Catalog gallery: one page listing every tool's outputs. Two views — a card grid
 * grouped into collapsible tool sections, or a single flat table across all tools.
 * Component-type + kind badges, a has-fixture chip, clickable EDAM tags, and an
 * "Open" link into the live detail view. Search + filters are client-side over the
 * embedded metadata; the type/kind filter and search reach inside `advanced_viz` to
 * the kind (e.g. volcano). Styling mirrors the Depictio viewer (colored section
 * title, Card/ThemeIcon, Mantine tokens — no hex chrome).
 */
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Code,
  Collapse,
  Divider,
  Drawer,
  Group,
  HoverCard,
  MultiSelect,
  Paper,
  Pill,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { ComponentRenderer, bulkComputeCards } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import {
  CATALOG_ACCENT,
  IdentityLink,
  ModulesMark,
  ToolLogo,
  TypeBadge,
  lastSeg,
  logoFor,
  metaFor,
} from './shared';
import type { OutputEntry, ToolEntry } from './shared';

type ViewMode = 'cards' | 'table';
type SortCol = 'tool' | 'output' | 'fixture';
type SortDir = 'asc' | 'desc';
const ACCENT = CATALOG_ACCENT;
const DASHBOARD_ID = 'catalog-preview';

/** Card-value maps for `card` renders, computed once and shared so each preview
 *  doesn't recompute. Mirrors OutputView's bulkComputeCards wiring. */
const CardValuesCtx = createContext<{
  values: Record<string, unknown>;
  secondary: Record<string, Record<string, unknown>>;
}>({ values: {}, secondary: {} });

/** Big-viz grid columns, driven by the gallery width toggle: full width → 3-up,
 *  normal (constrained) width → 2-up. */
const BigColsCtx = createContext<Record<string, number>>({ base: 1, sm: 2, lg: 3 });

/** Keep one failing render from blanking its whole card (and the gallery). */
class PreviewBoundary extends React.Component<
  { children: React.ReactNode },
  { failed?: boolean }
> {
  state: { failed?: boolean } = {};
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return (
        <Group justify="center" align="center" h="100%" c="dimmed" gap={6}>
          <Icon icon="mdi:image-broken-variant" width={20} />
          <Text size="xs">preview unavailable</Text>
        </Group>
      );
    }
    return this.props.children;
  }
}

/** "Big" renders deserve a roomy 2-up grid at chart height; "compact" ones
 *  (KPI cards, filters, text) pack into a dense multi-column row. */
const BIG_TYPES = new Set(['figure', 'advanced_viz', 'table', 'multiqc', 'map', 'image']);

/** Clip height per component type — KPI cards and interactive filters are short;
 *  figures / tables / advanced-viz get a tall tile to read as a real chart. */
const tileHeight = (ct: string): number =>
  ct === 'card' ? 150 : ct === 'interactive' ? 130 : ct === 'text' ? 104 : 380;

/** One render's live mini-preview: a labelled, clipped tile drawn by the REAL
 *  ComponentRenderer on the fixture (same renderer the detail view uses). Each
 *  tile lazy-mounts itself on scroll, so an output with 15 renders only mounts
 *  the tiles actually in view — no wall of simultaneous Plotly/grid instances. */
const RenderTile: React.FC<{
  m: StoredMetadata;
  toolId: string;
  outputId: string;
  onOpen: (id: string) => void;
}> = ({ m, toolId, outputId, onOpen }) => {
  const { values, secondary } = useContext(CardValuesCtx);
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || visible) return undefined;
    const io = new IntersectionObserver(
      (ents) => {
        if (ents.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: '250px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  const rec = m as Record<string, unknown>;
  const ct = rec.component_type as string;
  const note = rec._unsupported as string | undefined;
  const variant = rec._variant as string | undefined;
  const binds = rec._binds as Record<string, string> | undefined;
  // Readable render id (e.g. `shannon_card`) when the catalog declares one;
  // fall back to the positional index for renders without an explicit id.
  const renderId = (rec.render_id as string | null) || null;
  const label = renderId || m.index;
  // Big charts get a fixed clipped height (read as a thumbnail); cards / filters
  // size to their natural content so nothing gets cut off.
  const big = BIG_TYPES.has(ct);
  const h = tileHeight(ct);
  const useHandle = renderId ? `use: ${toolId}/${renderId}` : null;
  return (
    <Box
      ref={ref}
      style={{
        ...(big ? { height: h } : { minHeight: h }),
        display: 'flex',
        flexDirection: 'column',
        overflow: big ? 'hidden' : 'visible',
        borderRadius: 6,
        border: '1px solid var(--mantine-color-default-border)',
        background: 'var(--mantine-color-body)',
      }}
    >
      {/* Only the header navigates; the body stays a live, usable component. */}
      <Group
        justify="space-between"
        gap={6}
        px={8}
        py={5}
        wrap="nowrap"
        onClick={() => onOpen(outputId)}
        title="Open this component"
        style={{
          borderBottom: '1px solid var(--mantine-color-default-border)',
          flexShrink: 0,
          cursor: 'pointer',
        }}
      >
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <TypeBadge type={ct} size="sm" />
          <Text size="sm" fw={500} c="dimmed" truncate style={{ minWidth: 0 }}>
            {label}
          </Text>
        </Group>
        {/* hover to reveal this render's metadata — reference handle + column bindings */}
        <HoverCard width={330} shadow="md" openDelay={200} withinPortal position="top-end">
          <HoverCard.Target>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              style={{ flexShrink: 0 }}
              onClick={(e) => e.stopPropagation()}
            >
              <Icon icon="mdi:information-outline" width={16} />
            </ActionIcon>
          </HoverCard.Target>
          <HoverCard.Dropdown>
            <Stack gap={8}>
              <Group gap={6} wrap="wrap">
                <TypeBadge type={ct} size="xs" />
                {variant ? (
                  <Badge size="xs" variant="dot" color="gray">
                    {variant}
                  </Badge>
                ) : null}
              </Group>
              {useHandle ? (
                <div>
                  <Text size="xs" fw={600} c="dimmed">
                    Reference
                  </Text>
                  <Code block fz={11}>
                    {useHandle}
                  </Code>
                </div>
              ) : null}
              {binds && Object.keys(binds).length ? (
                <div>
                  <Text size="xs" fw={600} c="dimmed" mb={2}>
                    Column bindings
                  </Text>
                  <Stack gap={2}>
                    {Object.entries(binds).map(([role, col]) => (
                      <Text size="xs" key={role}>
                        <Text span c="dimmed">
                          {role}
                        </Text>{' '}
                        → <Code fz={11}>{col}</Code>
                      </Text>
                    ))}
                  </Stack>
                </div>
              ) : null}
              <Text size="xs" c="dimmed">
                Click the tile to open the full view.
              </Text>
            </Stack>
          </HoverCard.Dropdown>
        </HoverCard>
      </Group>
      <Box
        style={
          big
            ? { flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }
            : { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: 6 }
        }
      >
        {!visible ? (
          <Skeleton h={big ? '100%' : h - 40} radius={0} />
        ) : note ? (
          <Group justify="center" align="center" h="100%" c="dimmed" px="sm" ta="center">
            <Text size="xs">{note}</Text>
          </Group>
        ) : (
          <PreviewBoundary>
            <ComponentRenderer
              metadata={m}
              filters={[]}
              dashboardId={DASHBOARD_ID}
              cardValue={values[m.index]}
              cardSecondaryValues={secondary[m.index]}
              cardLoading={false}
            />
          </PreviewBoundary>
        )}
      </Box>
    </Box>
  );
};

/** Live preview of EVERY component an output renders as — each one its real
 *  component on the fixture. KPI `card` renders pack into a compact row; the rest
 *  (figures / tables / advanced-viz / interactive) stack full width. Each tile
 *  lazy-mounts independently (see RenderTile). */
const CardVizPreview: React.FC<{ entry: OutputEntry; toolId: string; onOpen: (id: string) => void }> = ({
  entry,
  toolId,
  onOpen,
}) => {
  const bigCols = useContext(BigColsCtx);
  const renders = entry.renders as unknown as StoredMetadata[];
  const outputId = entry.output.id;

  if (!entry.ok || renders.length === 0) {
    return (
      <Box style={{ background: 'var(--mantine-color-default-hover)' }}>
        <Group justify="center" align="center" h={140} c="dimmed" gap={6}>
          <Icon icon="mdi:flask-empty-outline" width={20} />
          <Text size="xs">{entry.ok ? 'no preview' : 'build failed'}</Text>
        </Group>
      </Box>
    );
  }

  const big = renders.filter((m) => BIG_TYPES.has((m as Record<string, unknown>).component_type as string));
  const compact = renders.filter((m) => !BIG_TYPES.has((m as Record<string, unknown>).component_type as string));

  return (
    <Box style={{ background: 'var(--mantine-color-default-hover)' }}>
      <Stack gap="md" p="sm">
        {big.length > 0 ? (
          <SimpleGrid cols={bigCols} spacing="md">
            {big.map((m) => (
              <RenderTile key={m.index} m={m} toolId={toolId} outputId={outputId} onOpen={onOpen} />
            ))}
          </SimpleGrid>
        ) : null}
        {compact.length > 0 ? (
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="xs">
            {compact.map((m) => (
              <RenderTile key={m.index} m={m} toolId={toolId} outputId={outputId} onOpen={onOpen} />
            ))}
          </SimpleGrid>
        ) : null}
      </Stack>
    </Box>
  );
};

/** Everything a free-text search should match for one output: its id/description,
 *  mode, recipe, find rule, fixture columns, and every render's variant + bindings
 *  (so searching a column like "CHROM" or a kind like "volcano" finds it). */
const searchBlob = (tool: ToolEntry, e: OutputEntry): string => {
  const o = e.output;
  const parts: string[] = [tool.id, tool.name, o.id, o.description || '', o.mode || '', o.recipe || ''];
  if (o.find) parts.push(JSON.stringify(o.find));
  if (o.columns) parts.push(...o.columns);
  for (const r of e.renders) {
    if (r._variant) parts.push(r._variant as string);
    const binds = r._binds as Record<string, string> | undefined;
    if (binds) parts.push(...Object.keys(binds), ...Object.values(binds));
  }
  return parts.join(' ').toLowerCase();
};

/** Component types, and — separately — the `advanced_viz` kinds (volcano,
 *  manhattan…). Kind is ONLY the advanced_viz `_variant`; a figure's plotly mode
 *  ("code"/"box") or a card aggregation is not a "kind" and gets no kind badge. */
const renderTags = (entry: OutputEntry): { types: string[]; kinds: string[] } => {
  const types: string[] = [];
  const kinds: string[] = [];
  for (const r of entry.renders) {
    const t = r.component_type as string;
    if (t && !types.includes(t)) types.push(t);
    if (t === 'advanced_viz') {
      const v = r._variant as string;
      if (v && !kinds.includes(v)) kinds.push(v);
    }
  }
  return { types, kinds };
};

/** Drop the redundant `<tool>_` prefix from an output id within its tool section
 *  (e.g. under "qiime2", `qiime2_alpha_diversity` → `alpha_diversity`). The full id
 *  stays the referenceable handle (tooltip + what `catalog preview <id>` takes). */
const shortId = (toolId: string, outId: string) =>
  outId.startsWith(`${toolId}_`) ? outId.slice(toolId.length + 1) : outId;

const FixtureChip: React.FC<{ has?: string | null }> = ({ has }) => (
  <Badge
    size="xs"
    variant="light"
    color={has ? 'teal' : 'gray'}
    leftSection={<Icon icon={has ? 'mdi:check-circle' : 'mdi:close-circle'} width={11} />}
  >
    {has ? 'fixture' : 'no fixture'}
  </Badge>
);

/** Component-type badges (Figure, Card, Advanced viz…). */
const TypeBadges: React.FC<{ types: string[] }> = ({ types }) => (
  <>
    {types.map((t) => (
      <TypeBadge key={t} type={t} size="xs" />
    ))}
  </>
);

/** Advanced-viz kind badges (volcano, manhattan…) — empty for non-advanced_viz. */
const KindBadges: React.FC<{ kinds: string[] }> = ({ kinds }) =>
  kinds.length ? (
    <>
      {kinds.map((k) => (
        <Badge key={k} size="xs" variant="dot" color="gray">
          {k}
        </Badge>
      ))}
    </>
  ) : (
    <Text size="xs" c="dimmed">
      —
    </Text>
  );

const OpenTitle: React.FC<{ entry: OutputEntry; label: string; onOpen: (id: string) => void }> = ({
  entry,
  label,
  onOpen,
}) => (
  <Tooltip label={entry.output.id} withinPortal openDelay={400}>
    {entry.ok ? (
      <Anchor
        component="button"
        type="button"
        fw={600}
        size="sm"
        ta="left"
        style={{ wordBreak: 'break-word', lineHeight: 1.25 }}
        onClick={() => onOpen(entry.output.id)}
      >
        {label}
      </Anchor>
    ) : (
      <Text fw={600} size="sm" style={{ wordBreak: 'break-word' }}>
        {label}
      </Text>
    )}
  </Tooltip>
);

const OpenButton: React.FC<{ entry: OutputEntry; onOpen: (id: string) => void }> = ({
  entry,
  onOpen,
}) => (
  <Button
    size="xs"
    variant="light"
    rightSection={<Icon icon="mdi:arrow-right" width={14} />}
    disabled={!entry.ok}
    onClick={() => onOpen(entry.output.id)}
    style={{ flexShrink: 0 }}
  >
    Open
  </Button>
);

const ToolNameLink: React.FC<{ tool: ToolEntry; inheritFont?: boolean }> = ({
  tool,
  inheritFont,
}) => {
  const href = tool.nf_core_url || tool.homepage || undefined;
  if (!href)
    return (
      <Text fw={inheritFont ? undefined : 500} size={inheritFont ? undefined : 'sm'} span>
        {tool.name}
      </Text>
    );
  return (
    <Anchor
      href={href}
      target="_blank"
      rel="noreferrer"
      title={href}
      inherit={inheritFont}
      size={inheritFont ? undefined : 'sm'}
      fw={inheritFont ? undefined : 500}
      onClick={(e) => e.stopPropagation()}
    >
      {tool.name}
    </Anchor>
  );
};

const OutputCard: React.FC<{ tool: ToolEntry; entry: OutputEntry; onOpen: (id: string) => void }> = ({
  tool,
  entry,
  onOpen,
}) => {
  const out = entry.output;
  const { types } = renderTags(entry);
  // Per-module collapse: a module (output) can have many renders, so each card
  // opens to reveal its render tiles. Default collapsed for a readable index.
  const [open, setOpen] = useState(false);
  const n = entry.renders.length;
  return (
    <Card withBorder radius="md" shadow="sm" padding={0} style={{ opacity: entry.ok ? 1 : 0.6, overflow: 'hidden' }}>
      {/* Header — click to expand this module's renders. */}
      <Group
        justify="space-between"
        wrap="nowrap"
        align="center"
        gap="sm"
        px="md"
        py="sm"
        style={{ cursor: 'pointer' }}
        onClick={() => setOpen((o) => !o)}
      >
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
          <Icon
            icon="mdi:chevron-right"
            width={20}
            style={{
              transform: open ? 'rotate(90deg)' : 'none',
              transition: 'transform 150ms',
              flexShrink: 0,
            }}
          />
          <Box style={{ minWidth: 0 }}>
            <Group gap={6} align="baseline" wrap="wrap">
              <Tooltip label={out.id} withinPortal openDelay={400}>
                <Text fw={600} size="sm" style={{ wordBreak: 'break-word' }}>
                  {shortId(tool.id, out.id)}
                </Text>
              </Tooltip>
              {out.mode ? (
                <Badge size="xs" variant="outline" color="gray">
                  {out.mode}
                </Badge>
              ) : null}
              <Badge size="xs" variant="light" color="gray" radius="sm">
                {n} render{n === 1 ? '' : 's'}
              </Badge>
            </Group>
            {out.description ? (
              <Text size="xs" c="dimmed" lineClamp={1}>
                {out.description}
              </Text>
            ) : null}
          </Box>
        </Group>
        <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
          <Group gap={6} wrap="nowrap" visibleFrom="sm">
            <TypeBadges types={types} />
          </Group>
          <FixtureChip has={out.fixture} />
          <OpenButton entry={entry} onOpen={onOpen} />
        </Group>
      </Group>
      <Collapse in={open}>
        <Divider />
        <CardVizPreview entry={entry} toolId={tool.id} onOpen={onOpen} />
        {!entry.ok && entry.error ? (
          <Box px="md" py="xs">
            <Text size="xs" c="red.6" lineClamp={2}>
              {entry.error}
            </Text>
          </Box>
        ) : null}
      </Collapse>
    </Card>
  );
};

const ToolSection: React.FC<{
  tool: ToolEntry;
  entries: OutputEntry[];
  opened: boolean;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
}> = ({ tool, entries, opened, onToggle, onOpen }) => (
  <Card withBorder radius="md" padding={0}>
    <Group
      justify="space-between"
      wrap="nowrap"
      gap="sm"
      px="md"
      py="sm"
      style={{ cursor: 'pointer' }}
      onClick={() => onToggle(tool.id)}
    >
      <Group gap="xs" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
        <ActionIcon variant="subtle" color="gray" aria-label={opened ? 'Collapse' : 'Expand'}>
          <Icon
            icon="mdi:chevron-right"
            width={20}
            style={{ transform: opened ? 'rotate(90deg)' : 'none', transition: 'transform 150ms' }}
          />
        </ActionIcon>
        <ToolLogo tool={tool} size={30} />
        <Title order={4} style={{ lineHeight: 1.1 }}>
          {tool.name}
        </Title>
        <Badge size="sm" variant="light" color="gray" radius="sm">
          {entries.length}
        </Badge>
      </Group>
      {tool.biotools_url ? (
        <Box onClick={(e) => e.stopPropagation()}>
          <IdentityLink
            href={tool.biotools_url}
            icon="mdi:wrench-outline"
            label={`bio.tools: ${lastSeg(tool.biotools_url)}`}
          />
        </Box>
      ) : null}
    </Group>
    <Collapse in={opened}>
      <Divider />
      <Box p="md">
        <Stack gap="md">
          {entries.map((e) => (
            <OutputCard key={e.output.id} tool={tool} entry={e} onOpen={onOpen} />
          ))}
        </Stack>
      </Box>
    </Collapse>
  </Card>
);

interface FlatRow {
  tool: ToolEntry;
  entry: OutputEntry;
}

const FlatTable: React.FC<{
  groups: { tool: ToolEntry; entries: OutputEntry[] }[];
  onOpen: (id: string) => void;
}> = ({ groups, onOpen }) => {
  const [sort, setSort] = useState<{ col: SortCol; dir: SortDir } | null>(null);

  const rows: FlatRow[] = groups.flatMap((g) => g.entries.map((entry) => ({ tool: g.tool, entry })));

  let sorted = rows; // default: tool-grouped declaration order
  if (sort) {
    const key = (r: FlatRow): string | number => {
      if (sort.col === 'tool') return r.tool.name.toLowerCase();
      if (sort.col === 'fixture') return r.entry.output.fixture ? 1 : 0;
      return r.entry.output.id.toLowerCase();
    };
    const factor = sort.dir === 'asc' ? 1 : -1;
    sorted = [...rows].sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      return ka < kb ? -factor : ka > kb ? factor : 0;
    });
  }

  const onSort = (col: SortCol) =>
    setSort((prev) =>
      prev && prev.col === col
        ? { col, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { col, dir: 'asc' },
    );

  const SortTh: React.FC<{ col: SortCol; width: string; children: React.ReactNode }> = ({
    col,
    width,
    children,
  }) => {
    const active = sort?.col === col;
    return (
      <Table.Th style={{ width, cursor: 'pointer', userSelect: 'none' }} onClick={() => onSort(col)}>
        <Group gap={4} wrap="nowrap">
          <span>{children}</span>
          <Icon
            icon={
              active
                ? sort?.dir === 'asc'
                  ? 'mdi:arrow-up'
                  : 'mdi:arrow-down'
                : 'mdi:unfold-more-horizontal'
            }
            width={13}
            color={active ? `var(--mantine-color-${ACCENT}-6)` : 'var(--mantine-color-dimmed)'}
          />
        </Group>
      </Table.Th>
    );
  };

  return (
    <Card withBorder radius="md" padding={0}>
      <Table.ScrollContainer minWidth={820}>
        <Table highlightOnHover verticalSpacing="sm" horizontalSpacing="md" stickyHeader>
          <Table.Thead>
            <Table.Tr>
              <SortTh col="tool" width="14%">
                Tool
              </SortTh>
              <SortTh col="output" width="26%">
                Output
              </SortTh>
              <Table.Th style={{ width: '26%' }}>Components</Table.Th>
              <Table.Th style={{ width: '18%' }}>Kind</Table.Th>
              <SortTh col="fixture" width="10%">
                Fixture
              </SortTh>
              <Table.Th style={{ width: '8%' }} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sorted.map(({ tool, entry }) => {
              const { types, kinds } = renderTags(entry);
              return (
                <Table.Tr key={entry.output.id} style={{ opacity: entry.ok ? 1 : 0.6 }}>
                  <Table.Td>
                    <ToolNameLink tool={tool} />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="wrap" align="baseline">
                      <OpenTitle entry={entry} label={shortId(tool.id, entry.output.id)} onOpen={onOpen} />
                      {entry.output.mode ? (
                        <Badge size="xs" variant="outline" color="gray">
                          {entry.output.mode}
                        </Badge>
                      ) : null}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="wrap">
                      <TypeBadges types={types} />
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="wrap">
                      <KindBadges kinds={kinds} />
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <FixtureChip has={entry.output.fixture} />
                  </Table.Td>
                  <Table.Td>
                    <OpenButton entry={entry} onOpen={onOpen} />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
};

const Gallery: React.FC<{ tools: ToolEntry[]; onOpen: (id: string) => void; theme?: string }> = ({
  tools,
  onOpen,
  theme,
}) => {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [kindFilter, setKindFilter] = useState<string[]>([]);
  const [toolFilter, setToolFilter] = useState<string[]>([]);
  const [fixtureOnly, setFixtureOnly] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  // Full-width content (3-up viz grid) vs constrained (2-up). Header stays put.
  // Default: constrained / 2 columns.
  const [wide, setWide] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Track collapsed sections (default: all collapsed — the page opens as a
  // readable tool index; expand a section to load its live previews).
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set(tools.map((t) => t.id)));

  // Card-render values for the live previews (computed once, same as OutputView).
  const [cardData, setCardData] = useState<{
    values: Record<string, unknown>;
    secondary: Record<string, Record<string, unknown>>;
  }>({ values: {}, secondary: {} });
  useEffect(() => {
    bulkComputeCards(DASHBOARD_ID, [])
      .then((r) =>
        setCardData({
          values: r.values as Record<string, unknown>,
          secondary: (r.secondary_values || {}) as Record<string, Record<string, unknown>>,
        }),
      )
      .catch(() => undefined);
  }, []);

  // Facet options carry counts (a histogram of the catalog — "Figure (1)",
  // "Advanced viz (12)") so the filters convey the catalog's shape at a glance.
  const { typeOptions, kindOptions, toolOptions } = useMemo(() => {
    const typeCt = new Map<string, number>();
    const kindCt = new Map<string, number>();
    const bump = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) || 0) + 1);
    tools.forEach((t) =>
      t.outputs.forEach((o) => {
        const { types, kinds } = renderTags(o);
        types.forEach((x) => bump(typeCt, x));
        kinds.forEach((x) => bump(kindCt, x));
      }),
    );
    return {
      typeOptions: [...typeCt].map(([v, n]) => ({ value: v, label: `${metaFor(v).name} (${n})` })),
      kindOptions: [...kindCt].map(([v, n]) => ({ value: v, label: `${v} (${n})` })),
      toolOptions: tools.map((t) => ({ value: t.id, label: `${t.name} (${t.outputs.length})` })),
    };
  }, [tools]);

  const totalOutputs = useMemo(() => tools.reduce((n, t) => n + t.outputs.length, 0), [tools]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tools
      .filter((t) => toolFilter.length === 0 || toolFilter.includes(t.id))
      .map((t) => {
        const entries = t.outputs.filter((o) => {
          if (fixtureOnly && !o.output.fixture) return false;
          const { types, kinds } = renderTags(o);
          if (typeFilter.length && !typeFilter.some((f) => types.includes(f))) return false;
          if (kindFilter.length && !kindFilter.some((f) => kinds.includes(f))) return false;
          if (q && !searchBlob(t, o).includes(q)) return false;
          return true;
        });
        return { tool: t, entries };
      })
      .filter((g) => g.entries.length > 0);
  }, [tools, query, typeFilter, kindFilter, toolFilter, fixtureOnly]);

  const hasFilters =
    query.trim() !== '' ||
    typeFilter.length > 0 ||
    kindFilter.length > 0 ||
    toolFilter.length > 0 ||
    fixtureOnly;
  const clearAll = () => {
    setQuery('');
    setTypeFilter([]);
    setKindFilter([]);
    setToolFilter([]);
    setFixtureOnly(false);
  };

  const shown = groups.reduce((n, g) => n + g.entries.length, 0);
  const shownToolIds = groups.map((g) => g.tool.id);
  const allCollapsed = shownToolIds.length > 0 && shownToolIds.every((id) => collapsed.has(id));

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const expandAll = () => setCollapsed(new Set());
  const collapseAll = () => setCollapsed(new Set(shownToolIds));

  return (
    <CardValuesCtx.Provider value={cardData}>
    <BigColsCtx.Provider value={wide ? { base: 1, sm: 2, lg: 3 } : { base: 1, sm: 2 }}>
    <Box p="lg">
      <Drawer
        opened={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        position="right"
        size="sm"
        title={
          <Group gap={8}>
            <Icon icon="mdi:tune-variant" width={18} />
            <Text fw={600}>Display settings</Text>
          </Group>
        }
      >
        <Stack gap="lg">
          <div>
            <Text size="sm" fw={600} mb={2}>
              Content width
            </Text>
            <Text size="xs" c="dimmed" mb="xs">
              Full uses the whole window (3 charts per row); Normal keeps a centered column (2 per
              row). Only the content widens — the header stays put.
            </Text>
            <SegmentedControl
              fullWidth
              value={wide ? 'wide' : 'normal'}
              onChange={(v) => setWide(v === 'wide')}
              data={[
                { value: 'normal', label: 'Normal' },
                { value: 'wide', label: 'Full' },
              ]}
            />
          </div>
          {/* room for more display settings here later */}
        </Stack>
      </Drawer>

      {/* Header / filters / controls stay constrained; only the content below widens. */}
      <Box style={{ maxWidth: 1280, margin: '0 auto' }}>
      <Group justify="space-between" align="center" wrap="nowrap" gap="md">
        <Group gap="md" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
          <img src={logoFor(theme)} alt="Depictio" style={{ height: 38, width: 'auto', flexShrink: 0 }} />
          <Divider orientation="vertical" style={{ height: 40 }} />
          <Box style={{ minWidth: 0 }}>
            <Group gap={10} wrap="nowrap" align="center">
              <ModulesMark size={42} />
              <Title order={2} c={ACCENT} style={{ lineHeight: 1.15 }}>
                Depictio Modules
              </Title>
            </Group>
            <Text size="sm" c="dimmed">
              Every tool output and the Depictio dashboard components it renders as — preview each
              live on its bundled fixture.
            </Text>
          </Box>
        </Group>
        <Badge variant="light" size="lg" color={ACCENT} radius="sm">
          {tools.length} tools · {totalOutputs} outputs
        </Badge>
      </Group>

      <Paper withBorder radius="md" p="md" mt="md" bg="var(--mantine-color-default-hover)">
        <Group gap="md" align="flex-end" wrap="wrap">
          <TextInput
            label="Search"
            placeholder="tool, output or kind (e.g. volcano)…"
            leftSection={<Icon icon="mdi:magnify" width={16} />}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            style={{ flex: 1, minWidth: 220 }}
          />
          <MultiSelect
            label="Type"
            placeholder="any"
            data={typeOptions}
            value={typeFilter}
            onChange={setTypeFilter}
            clearable
            style={{ minWidth: 160 }}
          />
          <MultiSelect
            label="Kind"
            placeholder="any"
            data={kindOptions}
            value={kindFilter}
            onChange={setKindFilter}
            searchable
            clearable
            style={{ minWidth: 160 }}
          />
          <MultiSelect
            label="Tool"
            placeholder="any"
            data={toolOptions}
            value={toolFilter}
            onChange={setToolFilter}
            clearable
            style={{ minWidth: 160 }}
          />
          <Switch
            label="Has fixture"
            checked={fixtureOnly}
            onChange={(e) => setFixtureOnly(e.currentTarget.checked)}
            mb={6}
          />
        </Group>
      </Paper>

      <Group justify="space-between" align="center" mt="md" wrap="wrap">
        <Text size="xs" c="dimmed">
          {shown < totalOutputs ? `Showing ${shown} of ${totalOutputs}` : `${totalOutputs} outputs`}
        </Text>
        <Group gap="sm" align="center">
          {viewMode === 'cards' ? (
            <Button
              size="compact-xs"
              variant="subtle"
              color="gray"
              leftSection={
                <Icon
                  icon={allCollapsed ? 'mdi:unfold-more-horizontal' : 'mdi:unfold-less-horizontal'}
                  width={14}
                />
              }
              onClick={allCollapsed ? expandAll : collapseAll}
              disabled={shownToolIds.length === 0}
            >
              {allCollapsed ? 'Expand all' : 'Collapse all'}
            </Button>
          ) : null}
          <SegmentedControl
            size="xs"
            value={viewMode}
            onChange={(v) => setViewMode(v as ViewMode)}
            data={[
              {
                value: 'cards',
                label: (
                  <Group gap={6} wrap="nowrap">
                    <Icon icon="mdi:view-grid-outline" width={15} />
                    <span>Cards</span>
                  </Group>
                ),
              },
              {
                value: 'table',
                label: (
                  <Group gap={6} wrap="nowrap">
                    <Icon icon="mdi:table" width={15} />
                    <span>Table</span>
                  </Group>
                ),
              },
            ]}
          />
          <Tooltip label="Display settings" withinPortal openDelay={300}>
            <ActionIcon
              variant="default"
              size="lg"
              aria-label="Display settings"
              onClick={() => setSettingsOpen(true)}
            >
              <Icon icon="mdi:tune-variant" width={17} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      {hasFilters ? (
        <Group gap={6} mt="sm" wrap="wrap" align="center">
          <Text size="xs" c="dimmed" fw={600}>
            Filters
          </Text>
          {query.trim() ? (
            <Pill withRemoveButton onRemove={() => setQuery('')}>
              “{query.trim()}”
            </Pill>
          ) : null}
          {typeFilter.map((v) => (
            <Pill key={v} withRemoveButton onRemove={() => setTypeFilter(typeFilter.filter((x) => x !== v))}>
              {metaFor(v).name}
            </Pill>
          ))}
          {kindFilter.map((v) => (
            <Pill key={v} withRemoveButton onRemove={() => setKindFilter(kindFilter.filter((x) => x !== v))}>
              {v}
            </Pill>
          ))}
          {toolFilter.map((v) => (
            <Pill key={v} withRemoveButton onRemove={() => setToolFilter(toolFilter.filter((x) => x !== v))}>
              {tools.find((t) => t.id === v)?.name || v}
            </Pill>
          ))}
          {fixtureOnly ? (
            <Pill withRemoveButton onRemove={() => setFixtureOnly(false)}>
              has fixture
            </Pill>
          ) : null}
          <Button size="compact-xs" variant="subtle" color="gray" onClick={clearAll}>
            Clear all
          </Button>
        </Group>
      ) : null}

      <Divider my="md" />
      </Box>

      {/* Content area: width follows the Normal/Full setting. */}
      <Box style={{ maxWidth: wide ? '100%' : 1280, margin: '0 auto' }}>
      {groups.length === 0 ? (
        <Stack align="center" py="xl" gap="sm">
          <ThemeIcon size={48} radius="xl" variant="light" color="gray">
            <Icon icon="mdi:filter-remove-outline" width={26} />
          </ThemeIcon>
          <Text c="dimmed">No outputs match your filters.</Text>
          {hasFilters ? (
            <Button
              variant="light"
              color={ACCENT}
              size="xs"
              leftSection={<Icon icon="mdi:filter-off-outline" width={14} />}
              onClick={clearAll}
            >
              Clear all filters
            </Button>
          ) : null}
        </Stack>
      ) : viewMode === 'table' ? (
        <FlatTable groups={groups} onOpen={onOpen} />
      ) : (
        <Stack gap="md">
          {groups.map((g) => (
            <ToolSection
              key={g.tool.id}
              tool={g.tool}
              entries={g.entries}
              opened={!collapsed.has(g.tool.id)}
              onToggle={toggle}
              onOpen={onOpen}
            />
          ))}
        </Stack>
      )}
      </Box>
    </Box>
    </BigColsCtx.Provider>
    </CardValuesCtx.Provider>
  );
};

export default Gallery;

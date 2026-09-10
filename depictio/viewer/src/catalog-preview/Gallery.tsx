/**
 * Catalog gallery: every tool's outputs, in three views.
 *
 * `split` (the default) is a two-pane browser — tool/output rail on the left, the
 * selected output rendering live on the right. It is the default because this is a
 * catalogue of *visualisations*, and the list views show none: they are text and
 * badges until you click through, so the page never answered its own question
 * ("what does this look like?") without a navigation. The split view answers it on
 * load. `cards` and `table` remain for scanning the whole catalogue at once.
 *
 * Component-type + kind badges, a has-fixture chip, clickable EDAM tags. Search +
 * filters are client-side over the embedded metadata; the type/kind filter and
 * search reach inside `advanced_viz` to the kind (e.g. volcano). Styling mirrors
 * the Depictio viewer (Card/ThemeIcon, Mantine tokens — no hex chrome).
 */
import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Chip,
  Collapse,
  Divider,
  Group,
  MultiSelect,
  Paper,
  Pill,
  ScrollArea,
  SegmentedControl,
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
import { CATALOG_ACCENT, IdentityLink, TypeBadge, lastSeg, logoFor, metaFor } from './shared';
import type { OutputEntry, ToolEntry } from './shared';
import OutputView from './OutputView';

type ViewMode = 'split' | 'cards' | 'table';
type SortCol = 'tool' | 'output' | 'fixture';
type SortDir = 'asc' | 'desc';
const ACCENT = CATALOG_ACCENT;

/** Said once under the facets, because the three of them do not count the same
 *  thing: a component type and a visualisation kind belong to a render, a tool
 *  owns outputs. */
const UNIT_HINT = 'Type and kind counts are renders; tool counts are outputs.';

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
  const { types, kinds } = renderTags(entry);
  const meta = metaFor(types[0] || '');
  return (
    <Card withBorder radius="md" shadow="sm" padding="md" style={{ opacity: entry.ok ? 1 : 0.6 }}>
      <Group justify="space-between" wrap="nowrap" align="flex-start" mb={6}>
        <Group gap="sm" wrap="nowrap" align="flex-start" style={{ minWidth: 0, flex: 1 }}>
          <ThemeIcon size={40} radius="md" variant="light" color={meta.color} style={{ flexShrink: 0 }}>
            <Icon icon={meta.icon} width={22} />
          </ThemeIcon>
          <Group gap={6} wrap="wrap" align="baseline" style={{ minWidth: 0 }}>
            <OpenTitle entry={entry} label={shortId(tool.id, out.id)} onOpen={onOpen} />
            {out.mode ? (
              <Badge size="xs" variant="outline" color="gray">
                {out.mode}
              </Badge>
            ) : null}
          </Group>
        </Group>
        <OpenButton entry={entry} onOpen={onOpen} />
      </Group>
      {out.description ? (
        <Text size="xs" c="dimmed" lineClamp={2}>
          {out.description}
        </Text>
      ) : null}
      <Group gap={6} wrap="wrap" mt="xs">
        <TypeBadges types={types} />
        {kinds.map((k) => (
          <Badge key={k} size="xs" variant="dot" color="gray">
            {k}
          </Badge>
        ))}
      </Group>
      <Group gap={6} wrap="wrap" mt={6}>
        <FixtureChip has={out.fixture} />
      </Group>
      {!entry.ok && entry.error ? (
        <Text size="xs" c="red.6" lineClamp={2} mt={6}>
          {entry.error}
        </Text>
      ) : null}
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
      {/* Sized by the width actually available, not by a viewport breakpoint.
          Mantine's responsive `cols` resolve against the document viewport, and
          in the docs this document IS the iframe — around 700px wide, under the
          `sm` breakpoint — so every card fell back to `base: 1` and drew full
          width however much room the page had. */}
      <Box
        p="md"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 'var(--mantine-spacing-md)',
        }}
      >
        {entries.map((e) => (
          <OutputCard key={e.output.id} tool={tool} entry={e} onOpen={onOpen} />
        ))}
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

/** One output as a row in the split browser's left rail: the short id, then the
 *  component types it renders as and any advanced-viz kinds. Deliberately terser
 *  than the card — the rail is a navigation surface, the pane carries the detail. */
const RailRow: React.FC<{
  toolId: string;
  entry: OutputEntry;
  selected: boolean;
  onClick: () => void;
}> = ({ toolId, entry, selected, onClick }) => {
  const { types, kinds } = renderTags(entry);
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      px="sm"
      py={6}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        border: 'none',
        cursor: 'pointer',
        background: selected ? 'var(--mantine-color-default-hover)' : 'transparent',
        borderLeft: `2px solid ${selected ? `var(--mantine-color-${ACCENT}-6)` : 'transparent'}`,
      }}
    >
      <Text size="sm" fw={selected ? 600 : 400} lineClamp={1} c={selected ? ACCENT : undefined}>
        {entry.output.name || shortId(toolId, entry.output.id)}
      </Text>
      <Group gap={4} mt={2} wrap="wrap">
        {types.map((t) => (
          <Box
            key={t}
            w={6}
            h={6}
            style={{ borderRadius: '50%', background: metaFor(t).color, flexShrink: 0 }}
          />
        ))}
        {kinds.map((k) => (
          <Text key={k} size="10px" c="dimmed" style={{ lineHeight: 1.4 }}>
            {k}
          </Text>
        ))}
      </Group>
    </Box>
  );
};

/** The split browser's left rail: filters on top, then one collapsible section
 *  per tool. Scrolls on its own so the pane beside it keeps its own position. */
const Rail: React.FC<{
  groups: { tool: ToolEntry; entries: OutputEntry[] }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  filters: React.ReactNode;
}> = ({ groups, selectedId, onSelect, collapsed, onToggle, filters }) => (
  <Box
    w="28%"
    miw={260}
    maw={400}
    style={{
      flexShrink: 0,
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      borderRight: '1px solid var(--mantine-color-default-border)',
    }}
  >
    <Box
      px="sm"
      py="sm"
      style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
    >
      {filters}
    </Box>
    {/* Native overflow, not Mantine's ScrollArea: this document is embedded in a
        fixed-height iframe on the docs site, where a custom-scrollbar container
        has previously failed to take the wheel. */}
    <Box style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
      {groups.length === 0 ? (
        <Text size="sm" c="dimmed" ta="center" py="xl">
          No outputs match your filters.
        </Text>
      ) : (
        groups.map((g) => {
          const opened = !collapsed.has(g.tool.id);
          return (
            <Box
              key={g.tool.id}
              style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
            >
              <Box
                component="button"
                type="button"
                onClick={() => onToggle(g.tool.id)}
                px="sm"
                py={8}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  width: '100%',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                }}
              >
                <Icon
                  icon={opened ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                  width={15}
                  color="var(--mantine-color-dimmed)"
                />
                <Text size="sm" fw={700} lineClamp={1} style={{ flex: 1, textAlign: 'left' }}>
                  {g.tool.name}
                </Text>
                <Badge size="xs" variant="light" color="gray" circle>
                  {g.entries.length}
                </Badge>
              </Box>
              <Collapse in={opened}>
                <Box pb={4}>
                  {g.entries.map((e) => (
                    <RailRow
                      key={e.output.id}
                      toolId={g.tool.id}
                      entry={e}
                      selected={e.output.id === selectedId}
                      onClick={() => onSelect(e.output.id)}
                    />
                  ))}
                </Box>
              </Collapse>
            </Box>
          );
        })
      )}
    </Box>
  </Box>
);

const Gallery: React.FC<{
  tools: ToolEntry[];
  /** Currently open output, or null. Owned by the app shell so the History API
   *  keeps driving it (#output= deep links, back/forward). */
  selected?: string | null;
  onOpen: (id: string | null) => void;
  theme?: string;
}> = ({ tools, selected = null, onOpen, theme }) => {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [kindFilter, setKindFilter] = useState<string[]>([]);
  const [toolFilter, setToolFilter] = useState<string[]>([]);
  const [fixtureOnly, setFixtureOnly] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('split');
  // Track collapsed sections (default: all open — a fresh tool shows expanded).
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  // A histogram of the catalog, so the facets convey its shape. Type and kind
  // count RENDERS — they are properties of a render, and one output ships four
  // cards — so the type counts sum to the catalogue's render total and the kind
  // counts to its advanced-viz renders. Tool counts outputs, which is what a
  // tool owns and what the rail's section badges already show. Each facet says
  // which of the two it is; leaving that unsaid is what made the numbers read
  // as arbitrary.
  const { typeOptions, kindOptions, toolOptions } = useMemo(() => {
    const typeCt = new Map<string, number>();
    const kindCt = new Map<string, number>();
    const bump = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) || 0) + 1);
    tools.forEach((t) =>
      t.outputs.forEach((o) =>
        o.renders.forEach((r) => {
          const type = r.component_type as string;
          if (!type) return;
          bump(typeCt, type);
          const variant = r._variant as string;
          if (type === 'advanced_viz' && variant) bump(kindCt, variant);
        }),
      ),
    );
    return {
      typeOptions: [...typeCt].map(([v, n]) => ({ value: v, label: metaFor(v).name, count: n })),
      kindOptions: [...kindCt].map(([v, n]) => ({ value: v, label: `${v} (${n})` })),
      toolOptions: tools.map((t) => ({ value: t.id, label: `${t.name} (${t.outputs.length})` })),
    };
  }, [tools]);

  // Outputs and renders both, everywhere the catalogue states its size. An
  // output is a table of numbers until something draws it, so "137 outputs"
  // undersells a catalogue that ships 547 ready visualisations — and it is the
  // visualisations a reader came to browse.
  const { totalOutputs, totalRenders, noFixtureCount } = useMemo(() => {
    let outputs = 0;
    let renders = 0;
    let noFixture = 0;
    for (const t of tools) {
      for (const o of t.outputs) {
        outputs += 1;
        renders += o.renders.length;
        if (!o.output.fixture) noFixture += 1;
      }
    }
    return { totalOutputs: outputs, totalRenders: renders, noFixtureCount: noFixture };
  }, [tools]);

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
  // The renders the facets actually select, not every render the surviving
  // outputs happen to carry: tick "Advanced viz 100" and the line has to read
  // 100, or the chip and the count contradict each other on the same screen.
  // Type and kind both narrow, except when both are set — "cards and volcanoes"
  // is a union, and reading it as an intersection would report zero.
  const shownRenders = useMemo(() => {
    const both = typeFilter.length > 0 && kindFilter.length > 0;
    let n = 0;
    for (const g of groups) {
      for (const e of g.entries) {
        for (const r of e.renders) {
          const type = r.component_type as string;
          const byType = typeFilter.length === 0 || typeFilter.includes(type);
          const byKind =
            kindFilter.length === 0 ||
            (type === 'advanced_viz' && kindFilter.includes(r._variant as string));
          if (both ? byType || byKind : byType && byKind) n += 1;
        }
      }
    }
    return n;
  }, [groups, typeFilter, kindFilter]);
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

  // The pane needs something to show on load: an empty right half is the same
  // "no visualisation on the page" failure the split view exists to fix. The
  // fallback does not touch history, so a #output= deep link still wins and the
  // back/forward buttons keep their meaning.
  const flatEntries = useMemo(() => groups.flatMap((g) => g.entries), [groups]);
  const paneEntry = flatEntries.find((e) => e.output.id === selected) ?? flatEntries[0];
  const paneId = paneEntry?.output.id ?? null;
  const paneToolId = groups.find((g) => g.entries.some((e) => e.output.id === paneId))?.tool.id;

  const activeFilterCount =
    typeFilter.length + kindFilter.length + toolFilter.length + (fixtureOnly ? 1 : 0);

  /** How much of the catalogue is on screen, in one wording used everywhere it
   *  is stated: the rail, the page header, and the top bar's totals. Outputs and
   *  renders always travel together and always in that order, so the two numbers
   *  can be compared between places instead of re-read. */
  const countLine = hasFilters
    ? `${shown} / ${totalOutputs} outputs · ${shownRenders} / ${totalRenders} renders`
    : `${totalOutputs} outputs · ${totalRenders} renders`;

  /** The one filter surface: stacked inside the rail's collapse, and a single
   *  wrapping toolbar row on a page.
   *
   * It used to exist twice and the copies had drifted (Kind and Tool searchable
   * in one, not the other), and both hid every count one click inside a
   * dropdown, so a panel written to "convey the catalog's shape at a glance"
   * conveyed nothing until opened. Component type is a chip row now: six values,
   * counts on their faces, one click to apply. Kind and Tool stay dropdowns
   * because 25 and 37 values are a list, not a shape.
   *
   * The page copy takes `search` so the text field sits in the same row as the
   * dropdowns instead of above them: as a labelled full-width field over two
   * half-page selects it was a form the height of the first tool section, and
   * the catalogue it filters started below the fold.
   *
   * `UNIT_HINT` states the units once for all three facets. A type or a kind is
   * a property of a render, not of an output — one output ships four cards — so
   * those count renders and add up to the catalogue's render total; a tool owns
   * outputs, which is what the section badges show. Leaving that unsaid was the
   * confusing part: six numbers that summed to neither total. */
  const facetPanel = (layout: 'stack' | 'row', search?: React.ReactNode) => {
    const wide = layout === 'row';
    const selects = (
      <>
        <MultiSelect
          label="Visualisation kind"
          placeholder={`any of ${kindOptions.length}`}
          data={kindOptions}
          value={kindFilter}
          onChange={setKindFilter}
          size="xs"
          w={wide ? 210 : undefined}
          searchable
          clearable
        />
        <MultiSelect
          label="Tool"
          placeholder={`any of ${toolOptions.length}`}
          data={toolOptions}
          value={toolFilter}
          onChange={setToolFilter}
          size="xs"
          w={wide ? 210 : undefined}
          searchable
          clearable
        />
      </>
    );
    const types = (
      <Box>
        <Text size="xs" fw={500} mb={4}>
          Component type
        </Text>
        <Chip.Group multiple value={typeFilter} onChange={setTypeFilter}>
          <Group gap={6}>
            {typeOptions.map((o) => (
              <Chip key={o.value} value={o.value} size="xs" variant="outline" color={ACCENT}>
                {o.label} {o.count}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
      </Box>
    );
    // Only offered when it can remove something. Every bundled output has a
    // fixture today, so an always-inert switch is one more control to read
    // past; a new output that ships without one brings it back.
    const fixture =
      noFixtureCount > 0 ? (
        <Switch
          size="xs"
          label="Has a fixture"
          description={`${noFixtureCount} without`}
          checked={fixtureOnly}
          onChange={(e) => setFixtureOnly(e.currentTarget.checked)}
        />
      ) : null;
    const hint = (
      <Text size="xs" c="dimmed">
        {UNIT_HINT}
      </Text>
    );
    if (wide) {
      return (
        <Stack gap={8}>
          <Group gap="md" align="flex-end" wrap="wrap">
            {search}
            {selects}
            {types}
            {fixture}
          </Group>
          {hint}
        </Stack>
      );
    }
    return (
      <Stack gap="sm">
        {types}
        {selects}
        {fixture}
        {hint}
      </Stack>
    );
  };

  const railFilters = (
    <Stack gap={6}>
      <TextInput
        placeholder="Search tool, output or kind…"
        leftSection={<Icon icon="mdi:magnify" width={16} />}
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        size="xs"
      />
      <Group justify="space-between" wrap="nowrap" gap={6}>
        {/* Opens in place rather than in a popover. The rail is 300px inside a
            fixed-height iframe, and a dropdown wide enough to hold the facets
            covered the list it filters and ran off the bottom of the document. */}
        <Button
          size="compact-xs"
          variant={activeFilterCount ? 'light' : 'subtle'}
          color={activeFilterCount ? ACCENT : 'gray'}
          leftSection={<Icon icon="mdi:filter-variant" width={14} />}
          rightSection={
            <Icon icon={filtersOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
          }
          onClick={() => setFiltersOpen((v) => !v)}
        >
          {activeFilterCount ? `Filters (${activeFilterCount})` : 'Filters'}
        </Button>
        {hasFilters ? (
          <Button size="compact-xs" variant="subtle" color="gray" onClick={clearAll}>
            Clear
          </Button>
        ) : null}
      </Group>
      <Text size="xs" c="dimmed">
        {countLine}
      </Text>
      <Collapse in={filtersOpen}>
        <Box pt={6} pb={4}>
          {facetPanel('stack')}
        </Box>
      </Collapse>
    </Stack>
  );

  const viewControl = (
    <SegmentedControl
      size="xs"
      value={viewMode}
      onChange={(v) => setViewMode(v as ViewMode)}
      data={[
        {
          value: 'split',
          label: (
            <Group gap={6} wrap="nowrap">
              <Icon icon="mdi:view-split-vertical" width={15} />
              <span>Browse</span>
            </Group>
          ),
        },
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
  );

  /* One compact bar, and the page's only branding.
   *
   * What it replaced repeated the logo and title of the docs hero directly above
   * the iframe, under a third name again ("Depictio Modules" where the page, the
   * nav and the app all say catalog), and it laid a nowrap row of hero text,
   * a count badge and a full-width button across a viewport it did not fit: at
   * iframe width both the badge and the button clipped mid-word. Here the two
   * right-hand groups never shrink and the title is what gives way. */
  const topBar = (
    <Group
      h={48}
      px="md"
      justify="space-between"
      wrap="nowrap"
      gap="md"
      style={{
        borderBottom: '1px solid var(--mantine-color-default-border)',
        flexShrink: 0,
      }}
    >
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
        <img
          src={logoFor(theme)}
          alt="Depictio"
          style={{ height: 20, width: 'auto', flexShrink: 0 }}
        />
        <Text fw={700} size="sm" style={{ whiteSpace: 'nowrap' }}>
          Tools Catalog
        </Text>
        <Text size="xs" c="dimmed" lineClamp={1}>
          · {tools.length} tools · {totalOutputs} outputs · {totalRenders} renders
        </Text>
      </Group>
      <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
        {viewControl}
        {/* Tool Studio — the no-backend web app to author a new tool entry.
            Hosted on GitHub Pages from the depictio-tool-studio showcase repo. */}
        <Button
          component="a"
          href="https://depictio.github.io/depictio-tool-studio/"
          target="_blank"
          rel="noreferrer"
          size="xs"
          variant="light"
          color={ACCENT}
          leftSection={<Icon icon="mdi:plus-box-outline" width={16} />}
          visibleFrom="md"
        >
          Contribute a tool
        </Button>
        <Tooltip label="Contribute a tool">
          <ActionIcon
            component="a"
            href="https://depictio.github.io/depictio-tool-studio/"
            target="_blank"
            rel="noreferrer"
            variant="light"
            color={ACCENT}
            hiddenFrom="md"
          >
            <Icon icon="mdi:plus-box-outline" width={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Group>
  );

  // ── Split browser ────────────────────────────────────────────────────────
  if (viewMode === 'split') {
    return (
      <Box
        style={{
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {topBar}
        <Group gap={0} wrap="nowrap" align="stretch" style={{ flex: 1, minHeight: 0 }}>
          <Rail
            groups={groups}
            selectedId={paneId}
            onSelect={onOpen}
            collapsed={collapsed}
            onToggle={toggle}
            filters={railFilters}
          />
          <Box style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto' }}>
            {paneEntry ? (
              <OutputView
                key={paneEntry.output.id}
                entry={paneEntry}
                theme={theme}
                variant="pane"
                toolId={paneToolId}
              />
            ) : (
              <Stack align="center" justify="center" h="100%" gap="sm" p="xl">
                <ThemeIcon size={48} radius="xl" variant="light" color="gray">
                  <Icon icon="mdi:filter-remove-outline" width={26} />
                </ThemeIcon>
                <Text c="dimmed">No outputs match your filters.</Text>
                {hasFilters ? (
                  <Button variant="light" color={ACCENT} size="xs" onClick={clearAll}>
                    Clear all filters
                  </Button>
                ) : null}
              </Stack>
            )}
          </Box>
        </Group>
      </Box>
    );
  }

  // ── Page views: an opened output takes the whole document ────────────────
  if (selected) {
    const entry = flatEntries.find((e) => e.output.id === selected)
      ?? tools.flatMap((t) => t.outputs).find((e) => e.output.id === selected);
    if (entry) {
      const owner = tools.find((t) => t.outputs.some((o) => o.output.id === selected));
      return (
        <OutputView
          entry={entry}
          theme={theme}
          toolId={owner?.id}
          onBack={() => onOpen(null)}
        />
      );
    }
  }

  return (
    <Box>
      {topBar}
      <Box p="lg" style={{ maxWidth: 1280, margin: '0 auto' }}>
        <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-default-hover)">
          {facetPanel(
            'row',
            <TextInput
              label="Search"
              placeholder="tool, output or kind…"
              leftSection={<Icon icon="mdi:magnify" width={16} />}
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
              size="xs"
              w={240}
            />,
          )}
        </Paper>

        <Group justify="space-between" align="center" mt="sm" wrap="wrap">
          <Text size="xs" c="dimmed">
            {countLine}
          </Text>
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
  );
};

export default Gallery;

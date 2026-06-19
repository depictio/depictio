/**
 * Catalog gallery: one page listing every tool's outputs. Two views — a card grid
 * grouped into collapsible tool sections, or a single flat table across all tools.
 * Component-type + kind badges, a has-fixture chip, clickable EDAM tags, and an
 * "Open" link into the live detail view. Search + filters are client-side over the
 * embedded metadata; the type/kind filter and search reach inside `advanced_viz` to
 * the kind (e.g. volcano). Styling mirrors the Depictio viewer (colored section
 * title, Card/ThemeIcon, Mantine tokens — no hex chrome).
 */
import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Collapse,
  Divider,
  Group,
  MultiSelect,
  Paper,
  Pill,
  SegmentedControl,
  SimpleGrid,
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

type ViewMode = 'cards' | 'table';
type SortCol = 'tool' | 'output' | 'fixture';
type SortDir = 'asc' | 'desc';
const ACCENT = CATALOG_ACCENT;

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
      <Box p="md">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          {entries.map((e) => (
            <OutputCard key={e.output.id} tool={tool} entry={e} onOpen={onOpen} />
          ))}
        </SimpleGrid>
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
  // Track collapsed sections (default: all open — a fresh tool shows expanded).
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

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
    <Box p="lg" style={{ maxWidth: 1280, margin: '0 auto' }}>
      <Group justify="space-between" align="center" wrap="nowrap" gap="md">
        <Group gap="md" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
          <img src={logoFor(theme)} alt="Depictio" style={{ height: 38, width: 'auto', flexShrink: 0 }} />
          <Divider orientation="vertical" style={{ height: 40 }} />
          <Box style={{ minWidth: 0 }}>
            <Title order={2} c={ACCENT} style={{ lineHeight: 1.15 }}>
              Depictio Modules
            </Title>
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
  );
};

export default Gallery;

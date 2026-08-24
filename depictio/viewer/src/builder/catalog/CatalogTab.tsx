import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Chip,
  Group,
  Loader,
  Popover,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { CatalogModule, CatalogOutputMatch, CatalogRender } from 'depictio-react-core';
import { fetchCatalogCompose, upsertComponent } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ComponentType } from '../store/useBuilderStore';
import { buildMetadata } from '../buildMetadata';
import CatalogPreviewPanel, { catalogUseRef } from './CatalogPreviewPanel';

interface CatalogTabProps {
  projectId: string;
}

const COMPONENT_COLORS: Record<string, string> = {
  figure:       'blue',
  card:         'teal',
  table:        'gray',
  interactive:  'lime',
  advanced_viz: 'violet',
  multiqc:      'orange',
};

const COMPONENT_LABELS: Record<string, string> = {
  figure:       'Figure',
  card:         'Card',
  table:        'Table',
  advanced_viz: 'Advanced viz',
  multiqc:      'MultiQC',
};

function buildConfigFromRender(render: CatalogRender): Record<string, unknown> {
  if (render.component === 'advanced_viz') {
    // `preset_config` carries the catalog preview's computed config (role
    // bindings + data-derived viz-control defaults). buildMetadata overlays its
    // non-role extras so the added component renders exactly like its preview.
    return {
      viz_kind: render.kind ?? null,
      column_mapping: render.roles ?? {},
      preset_config: render.config ?? null,
    };
  }
  if (render.component === 'figure') {
    return {
      visu_type: render.visu_type ?? 'scatter',
      dict_kwargs: render.dict_kwargs ?? {},
      ...(render.code ? { code_content: render.code, mode: 'code' } : { mode: 'ui' }),
    };
  }
  if (render.component === 'card') {
    // CardBuilder reads column_name (not column) from config. Everything after
    // the first two lines is the secondary strip: the catalog can declare it and
    // the preview renders it, so dropping it here made Add produce a plain
    // number where the preview had just shown a box plot / histogram / top-N.
    return {
      column_name: render.column ?? null,
      aggregation: render.aggregation ?? null,
      ...(render.aggregations?.length ? { aggregations: render.aggregations } : {}),
      ...(render.secondary_layout ? { secondary_layout: render.secondary_layout } : {}),
      ...(render.breakdown_col ? { breakdown_col: render.breakdown_col } : {}),
      ...(render.top_n_count != null ? { top_n_count: render.top_n_count } : {}),
      ...(render.coverage_max != null ? { coverage_max: render.coverage_max } : {}),
      ...(render.threshold_value != null ? { threshold_value: render.threshold_value } : {}),
      ...(render.threshold_direction
        ? { threshold_direction: render.threshold_direction }
        : {}),
      ...(render.threshold_warn != null ? { threshold_warn: render.threshold_warn } : {}),
      ...(render.attrition_cols?.length ? { attrition_cols: render.attrition_cols } : {}),
      ...(render.trend_col ? { trend_col: render.trend_col } : {}),
      ...(render.filter_expr ? { filter_expr: render.filter_expr } : {}),
    };
  }
  if (render.component === 'interactive') {
    return {
      interactive_component_type: render.interactive_type ?? null,
      column_name: render.column_name ?? null,
    };
  }
  if (render.component === 'table') {
    // The builder keeps per-column visibility as a bag; the catalog states the
    // visible list, so anything it doesn't name is hidden.
    const colsJson = render.columns?.length
      ? Object.fromEntries(
          (render.columns ?? []).map((name) => [name, { hide: false }]),
        )
      : undefined;
    return {
      ...(colsJson ? { cols_json: colsJson } : {}),
      ...(render.page_size != null ? { page_size: render.page_size } : {}),
      ...(render.row_selection_enabled != null
        ? { row_selection_enabled: render.row_selection_enabled }
        : {}),
      ...(render.row_selection_column
        ? { row_selection_column: render.row_selection_column }
        : {}),
    };
  }
  return {};
}

// ---------------------------------------------------------------------------
// Match row in the left list
// ---------------------------------------------------------------------------

interface MatchRowProps {
  match: CatalogOutputMatch;
  selected: boolean;
  onClick: () => void;
}

const MatchRow: React.FC<MatchRowProps> = ({ match, selected, onClick }) => {
  // The identifiers and the full sentence are what made every row four lines
  // tall. The row shows the catalog's own short `name`; the sentence and the
  // ids go to the tooltip. `renders_as` becomes coloured dots — the count and
  // the mix of component types are legible at a glance, the labels were not
  // worth a line.
  const detail = (
    <Stack gap={2}>
      <Text size="xs">{match.description || match.output_id}</Text>
      <Text size="xs" c="dimmed" ff="monospace">{match.output_id}</Text>
      <Text size="xs" c="dimmed">collection: {match.dc_tag}</Text>
      <Text size="xs" c="dimmed">
        {match.renders_as.map((r) => COMPONENT_LABELS[r.component] ?? r.component).join(' · ')}
      </Text>
    </Stack>
  );
  return (
    <Tooltip label={detail} withArrow position="right" openDelay={350} multiline maw={340}>
      <UnstyledButton
        onClick={onClick}
        w="100%"
        px="md"
        py={7}
        style={{
          borderLeft: `3px solid ${selected ? 'var(--mantine-color-violet-6)' : 'transparent'}`,
          background: selected ? 'var(--mantine-color-violet-0)' : 'transparent',
          transition: 'background 120ms',
        }}
      >
        <Group gap={6} wrap="nowrap" align="center">
          <Text size="sm" fw={selected ? 600 : 400} lineClamp={1} style={{ flex: 1, minWidth: 0 }}>
            {match.name || match.output_id}
          </Text>
          <Group gap={3} wrap="nowrap" style={{ flexShrink: 0 }}>
            {match.renders_as.map((r, i) => (
              <Box
                key={i}
                w={7}
                h={7}
                style={{
                  borderRadius: '50%',
                  background: `var(--mantine-color-${COMPONENT_COLORS[r.component] ?? 'gray'}-6)`,
                }}
              />
            ))}
          </Group>
        </Group>
      </UnstyledButton>
    </Tooltip>
  );
};

// ---------------------------------------------------------------------------
// Tool section header
// ---------------------------------------------------------------------------

const ToolLabel: React.FC<{ module: CatalogModule; count: number }> = ({ module, count }) => (
  <Group gap="sm" wrap="nowrap">
    <Icon icon="mdi:toolbox-outline" width={16} color="var(--mantine-color-violet-6)" />
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={700} lineClamp={1}>
        {module.tool_name}
      </Text>
      <Text size="xs" c="dimmed" lineClamp={1} style={{ fontFamily: 'monospace', fontSize: 10 }}>
        {module.tool_id}
      </Text>
    </Stack>
    <Badge size="xs" variant="light" color="violet" ml="auto" style={{ flexShrink: 0 }}>
      {count}
    </Badge>
  </Group>
);

// ---------------------------------------------------------------------------
// Facet filter group — a labelled Chip.Group with per-option counts
// ---------------------------------------------------------------------------

interface FacetProps {
  label: string;
  options: { value: string; label: string; count: number }[];
  selected: string[];
  onChange: (values: string[]) => void;
}

const Facet: React.FC<FacetProps> = ({ label, options, selected, onChange }) => {
  if (options.length <= 1) return null; // nothing to filter on
  return (
    <Box>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={6}>
        {label}
      </Text>
      <Chip.Group multiple value={selected} onChange={onChange}>
        <Group gap={6}>
          {options.map((o) => (
            <Chip key={o.value} value={o.value} size="xs" variant="outline" color="violet" radius="sm">
              {o.label} <Text span c="dimmed" fz={10}>({o.count})</Text>
            </Chip>
          ))}
        </Group>
      </Chip.Group>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const CatalogTab: React.FC<CatalogTabProps> = ({ projectId }) => {
  const [modules, setModules] = useState<CatalogModule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<CatalogOutputMatch | null>(null);
  const [selectedToolId, setSelectedToolId] = useState('');
  const [selectedToolName, setSelectedToolName] = useState('');
  const [search, setSearch] = useState('');

  // Facet filters, auto-derived from the compose result (see facet options
  // below). There is deliberately no tool facet: the accordion already groups
  // by tool, and its headers carried exactly the same counts.
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [dcFilter, setDcFilter] = useState<string[]>([]);
  // Which tool accordion items are expanded (controlled — start all-open).
  const [openTools, setOpenTools] = useState<string[]>([]);

  const initFromCatalog = useBuilderStore((s) => s.initFromCatalog);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const componentId = useBuilderStore((s) => s.componentId);

  useEffect(() => {
    if (!projectId) return;
    fetchCatalogCompose(projectId)
      .then((r) => {
        setModules(r.modules);
        setOpenTools(r.modules.map((m) => m.tool_id)); // start with every tool open
        if (r.modules.length > 0 && r.modules[0].matches.length > 0) {
          setSelectedMatch(r.modules[0].matches[0]);
          setSelectedToolId(r.modules[0].tool_id);
          setSelectedToolName(r.modules[0].tool_name);
        }
      })
      .catch((e: unknown) => setError(String(e)));
  }, [projectId]);

  // ── Facet options with counts (from the full, unfiltered module set) ──────
  const facetOptions = useMemo(() => {
    const types = new Map<string, number>();
    const dcs = new Map<string, number>();
    for (const mod of modules ?? []) {
      for (const m of mod.matches) {
        dcs.set(m.dc_tag, (dcs.get(m.dc_tag) ?? 0) + 1);
        const seen = new Set<string>();
        for (const r of m.renders_as) {
          if (seen.has(r.component)) continue;
          seen.add(r.component);
          types.set(r.component, (types.get(r.component) ?? 0) + 1);
        }
      }
    }
    return {
      types: [...types.entries()]
        .map(([value, count]) => ({ value, label: COMPONENT_LABELS[value] ?? value, count }))
        .sort((a, b) => a.label.localeCompare(b.label)),
      dcs: [...dcs.entries()]
        .map(([value, count]) => ({ value, label: value, count }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    };
  }, [modules]);

  const activeFacetCount = typeFilter.length + dcFilter.length;
  const anyFilterActive = search.trim() !== '' || activeFacetCount > 0;

  const clearFilters = () => {
    setSearch('');
    setTypeFilter([]);
    setDcFilter([]);
  };

  // ── Apply search + facets ─────────────────────────────────────────────────
  const filteredModules = useMemo<CatalogModule[]>(() => {
    if (!modules) return [];
    const q = search.trim().toLowerCase();
    const matchPasses = (mod: CatalogModule, m: CatalogOutputMatch): boolean => {
      if (dcFilter.length && !dcFilter.includes(m.dc_tag)) return false;
      if (typeFilter.length && !m.renders_as.some((r) => typeFilter.includes(r.component)))
        return false;
      if (!q) return true;
      return (
        mod.tool_name.toLowerCase().includes(q) ||
        mod.tool_id.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.output_id.toLowerCase().includes(q) ||
        m.dc_tag.toLowerCase().includes(q)
      );
    };
    return modules
      .map((mod) => ({ ...mod, matches: mod.matches.filter((m) => matchPasses(mod, m)) }))
      .filter((mod) => mod.matches.length > 0);
  }, [modules, search, typeFilter, dcFilter]);

  const selectMatch = (mod: CatalogModule, match: CatalogOutputMatch) => {
    setSelectedMatch(match);
    setSelectedToolId(mod.tool_id);
    setSelectedToolName(mod.tool_name);
  };

  const handleAdd = (match: CatalogOutputMatch, toolId: string, toolName: string) =>
    (render: CatalogRender) => {
      initFromCatalog({
        componentType: render.component as ComponentType,
        wfId: match.wf_id,
        dcId: match.dc_id,
        projectId,
        config: buildConfigFromRender(render),
        source: {
          toolId,
          toolName,
          outputId: match.output_id,
          description: match.description,
          use: catalogUseRef(toolId, match.output_id, render),
        },
      });
    };

  // Quick-add: pre-fill store, build metadata, save to backend, navigate.
  const handleDirectAdd = (match: CatalogOutputMatch, toolId: string, toolName: string) =>
    async (render: CatalogRender) => {
      if (!dashboardId || !componentId) return;
      initFromCatalog({
        componentType: render.component as ComponentType,
        wfId: match.wf_id,
        dcId: match.dc_id,
        projectId,
        config: buildConfigFromRender(render),
        source: {
          toolId,
          toolName,
          outputId: match.output_id,
          description: match.description,
          use: catalogUseRef(toolId, match.output_id, render),
        },
      });
      // Zustand set() is synchronous — read the updated state immediately.
      const state = useBuilderStore.getState();
      try {
        const metadata = buildMetadata(state);
        await upsertComponent(dashboardId, metadata, { appendLayout: true });
        window.location.assign(`/dashboard-edit/${dashboardId}`);
      } catch {
        // Fall back to Edit & Add so the user can fix the issue in the Design step.
        // (initFromCatalog is already called above, so the Design step will show.)
      }
    };

  // The three pre-list states fill the surface the browser occupies, the same
  // way the split panel below does. `py="xl"` alone left them pinned to the top
  // of an otherwise empty screen.
  // ── Loading ──────────────────────────────────────────────────────────────
  if (!modules && !error) {
    return (
      <Center style={{ flex: 1 }} mih={520}>
        <Stack align="center" gap={4}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Matching your data against the catalog…</Text>
        </Stack>
      </Center>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <Center style={{ flex: 1 }} mih={520}>
        <Alert color="red" title="Could not load catalog">{error}</Alert>
      </Center>
    );
  }

  // ── Empty ────────────────────────────────────────────────────────────────
  if (modules?.length === 0) {
    return (
      <Center style={{ flex: 1 }} mih={520}>
        <Box
          maw={480}
          w="100%"
          style={{
            border: '1px solid var(--mantine-color-default-border)',
            borderRadius: 12,
            padding: '48px 40px',
            textAlign: 'center',
          }}
        >
          <Stack align="center" gap="lg">
            <Icon icon="mdi:archive-off-outline" width={56} color="var(--mantine-color-gray-5)" />
            <Title order={2} fw={700}>No catalog matches</Title>
            <Text size="md" c="dimmed">
              None of the ingested data collections matched a known catalog tool. Make sure the
              relevant files are ingested and their paths follow the expected patterns.
            </Text>
          </Stack>
        </Box>
      </Center>
    );
  }

  // ── Split panel ──────────────────────────────────────────────────────────
  return (
    <Group
      align="flex-start"
      gap={0}
      wrap="nowrap"
      style={{
        height: '100%',
        minHeight: 520,
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 12,
        overflow: 'hidden',
      }}
    >
      {/* ── Left panel (≈1/4) — search + facets + tool accordion ── */}
      <Box
        w="26%"
        miw={300}
        maw={420}
        h="100%"
        style={{
          borderRight: '1px solid var(--mantine-color-default-border)',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Search + facets */}
        <Box px="md" py="sm" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
          <TextInput
            placeholder="Search tools, outputs, files…"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            leftSection={<Icon icon="mdi:magnify" width={16} />}
            rightSection={
              search ? (
                <UnstyledButton onClick={() => setSearch('')} style={{ display: 'flex' }}>
                  <Icon icon="mdi:close-circle" width={14} color="var(--mantine-color-dimmed)" />
                </UnstyledButton>
              ) : null
            }
            size="sm"
          />

          {/* Facets behind a disclosure: fully expanded they cost ~185px above
            * the list, which is most of what a narrow panel has to show results
            * in. The badge keeps a hidden filter from being a mystery. */}
          {(facetOptions.types.length > 1 || facetOptions.dcs.length > 1) && (
            <Group justify="space-between" mt={6} wrap="nowrap">
              <Popover position="bottom-start" withArrow shadow="md" width={300}>
                <Popover.Target>
                  <Button
                    size="compact-xs"
                    variant={activeFacetCount ? 'light' : 'subtle'}
                    color={activeFacetCount ? 'violet' : 'gray'}
                    leftSection={<Icon icon="mdi:filter-variant" width={14} />}
                    rightSection={
                      activeFacetCount ? (
                        <Badge size="xs" circle variant="filled" color="violet">
                          {activeFacetCount}
                        </Badge>
                      ) : null
                    }
                  >
                    Filters
                  </Button>
                </Popover.Target>
                <Popover.Dropdown p="sm">
                  <Stack gap="sm">
                    <Facet label="Component" options={facetOptions.types} selected={typeFilter} onChange={setTypeFilter} />
                    <Facet label="Data collection" options={facetOptions.dcs} selected={dcFilter} onChange={setDcFilter} />
                  </Stack>
                </Popover.Dropdown>
              </Popover>

              {anyFilterActive && (
                <UnstyledButton onClick={clearFilters}>
                  <Group gap={4}>
                    <Icon icon="mdi:filter-remove-outline" width={13} color="var(--mantine-color-violet-6)" />
                    <Text size="xs" c="violet" fw={600}>Clear</Text>
                  </Group>
                </UnstyledButton>
              )}
            </Group>
          )}
        </Box>

        {/* Accordion grouped by tool */}
        <ScrollArea style={{ flex: 1 }}>
          {filteredModules.length === 0 ? (
            <Center py="xl">
              <Text size="sm" c="dimmed">No results for the current filters</Text>
            </Center>
          ) : (
            <Accordion
              multiple
              value={openTools}
              onChange={setOpenTools}
              variant="default"
              chevronPosition="left"
              styles={{
                control: { paddingLeft: 8, paddingRight: 8, paddingTop: 6, paddingBottom: 6 },
                label: { padding: 0 },
                item: { borderBottom: '1px solid var(--mantine-color-default-border)' },
                panel: { padding: 0 },
              }}
            >
              {filteredModules.map((module) => (
                <Accordion.Item key={module.tool_id} value={module.tool_id}>
                  <Accordion.Control>
                    <ToolLabel module={module} count={module.matches.length} />
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Stack gap={0}>
                      {module.matches.map((match) => {
                        const isSelected =
                          selectedMatch?.output_id === match.output_id &&
                          selectedMatch?.dc_id === match.dc_id;
                        return (
                          <MatchRow
                            key={`${match.dc_id}-${match.output_id}`}
                            match={match}
                            selected={isSelected}
                            onClick={() => selectMatch(module, match)}
                          />
                        );
                      })}
                    </Stack>
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          )}
        </ScrollArea>
      </Box>

      {/* ── Right panel (≈3/4) — per-render preview cards ── */}
      <Box style={{ flex: 1, minWidth: 0, overflow: 'hidden' }} h="100%">
        {selectedMatch ? (
          <CatalogPreviewPanel
            match={selectedMatch}
            toolId={selectedToolId}
            toolName={selectedToolName}
            onAdd={handleAdd(selectedMatch, selectedToolId, selectedToolName)}
            onDirectAdd={handleDirectAdd(selectedMatch, selectedToolId, selectedToolName)}
          />
        ) : (
          <Center h="100%">
            <Text c="dimmed">Select an output on the left to preview</Text>
          </Center>
        )}
      </Box>
    </Group>
  );
};

export default CatalogTab;

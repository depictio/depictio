/**
 * Builder for the advanced_viz component family.
 *
 * Two-step inside the per-type panel:
 *   1) Pick viz_kind. The backend's graded suggestion engine ranks every kind
 *      for the bound DC; the picker surfaces the strong matches under
 *      "Recommended" (with a fit score) and the rest under "Other
 *      visualisations". Nothing is hidden or disabled — the user can pick any
 *      kind and bind columns manually ("suggest but tolerate").
 *   2) Bind each required role to a column from the chosen DC. Accepted dtypes
 *      and the candidate pre-fill both come from the backend (single source of
 *      truth — see /advanced_viz/kinds and /datacollections/viz-suggestions),
 *      so the TS side never duplicates the schema. A castable-but-inexact dtype
 *      (e.g. Int for a Float role) is a tolerant warning, not a blocker.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Divider,
  Group,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  AdvancedVizKind,
  AdvancedVizKindDescriptor,
  VizKindSuggestion,
  fetchAdvancedVizKinds,
  fetchPolarsSchema,
  fetchVizSuggestions,
} from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import AdvancedVizPreview from './AdvancedVizPreview';

/** Acceptable polars dtype names per canonical role (mirrors
 *  depictio/models/components/advanced_viz/schemas.py). */
const NUMERIC_FLOAT = ['Float32', 'Float64'];
const NUMERIC_INT = [
  'Int8',
  'Int16',
  'Int32',
  'Int64',
  'UInt8',
  'UInt16',
  'UInt32',
  'UInt64',
];
const NUMERIC_ANY = [...NUMERIC_INT, ...NUMERIC_FLOAT];
const STRING_LIKE = ['String', 'Utf8'];

// Score at/above which a kind is surfaced under "Recommended" (mirrors
// RECOMMENDED_SCORE in depictio/models/components/advanced_viz/schemas.py).
const RECOMMENDED_SCORE = 0.8;

// Dtype compatibility for a chosen column, mirroring the cast tiers in the
// backend scoring engine (schemas.py `_dtype_score`): an Int column feeds a
// Float role and Categorical feeds a String role — both as tolerant
// "castable" matches that surface a warning rather than blocking save.
const _FLOAT_SET = new Set(NUMERIC_FLOAT);
const _INT_SET = new Set(NUMERIC_INT);
const _STRING_SET = new Set(STRING_LIKE);
type DtypeMatch = 'exact' | 'castable' | 'none';
function dtypeMatch(actual: string, accepted: string[]): DtypeMatch {
  if (accepted.includes(actual)) return 'exact';
  if (accepted.length > 0 && accepted.every((d) => _FLOAT_SET.has(d)) && _INT_SET.has(actual))
    return 'castable';
  if (actual === 'Categorical' && accepted.some((d) => _STRING_SET.has(d))) return 'castable';
  return 'none';
}

// Colour scheme shared by the bindings table + tooltip so required/optional
// reads consistently. Required uses a warm accent, optional stays muted.
const REQUIRED_COLOR = 'red';
const OPTIONAL_COLOR = 'gray';

/** Friendly one-word category for a role's accepted polars dtypes, so the
 *  bindings overview reads "text"/"number" instead of "String / Utf8". */
function simplifyDtypes(dtypes: string[]): string {
  if (dtypes.length === 0) return 'any';
  const allIn = (arr: string[]) => dtypes.every((d) => arr.includes(d));
  const some = (arr: string[]) => dtypes.some((d) => arr.includes(d));
  if (allIn(STRING_LIKE)) return 'text';
  if (allIn(NUMERIC_FLOAT)) return 'decimal';
  if (allIn(NUMERIC_INT)) return 'integer';
  if (allIn(NUMERIC_ANY)) return 'number';
  if (some(STRING_LIKE) && some(NUMERIC_ANY)) return 'text / number';
  return dtypes.join(' / ');
}

/** Live-compute embedding gate — wide feature-matrix DCs (sample_id + many
 *  numeric features) should make Embedding available so the renderer can
 *  dispatch a Celery PCA/UMAP/t-SNE/PCoA task. Without this, embedding_features
 *  (80 numeric cols, no precomputed dim_1/dim_2) was rejected by every kind. */
const EMBEDDING_LIVE_MIN_NUMERIC = 10;

type EmbeddingMode = 'precomputed' | 'live';
function detectEmbeddingMode(
  schema: Record<string, string>,
): EmbeddingMode | null {
  const lower = Object.entries(schema).reduce<Record<string, string>>(
    (acc, [name, dtype]) => {
      acc[name.toLowerCase()] = dtype;
      return acc;
    },
    {},
  );
  const hasNamedDtype = (aliases: string[], accepted: string[]): boolean =>
    aliases.some((a) => lower[a] != null && accepted.includes(lower[a]));
  // Embedding-specific name hints — the only inline aliases the builder still
  // keeps, used to tell precomputed (dim_1/dim_2 columns) from live-compute
  // mode (wide numeric matrix). Generic role/dtype tables live backend-side.
  const hasSample = hasNamedDtype(['sample_id', 'sample', 'sampleid', 'sample_name'], STRING_LIKE);
  if (!hasSample) return null;
  const hasDim1 = hasNamedDtype(['dim_1', 'pc1', 'umap1', 'tsne1', 'x'], NUMERIC_FLOAT);
  const hasDim2 = hasNamedDtype(['dim_2', 'pc2', 'umap2', 'tsne2', 'y'], NUMERIC_FLOAT);
  if (hasDim1 && hasDim2) return 'precomputed';
  const numericCount = Object.values(schema).filter((d) =>
    NUMERIC_ANY.includes(d),
  ).length;
  return numericCount >= EMBEDDING_LIVE_MIN_NUMERIC ? 'live' : null;
}

/** Compact binding label: just the role name, with an info icon whose rich
 *  tooltip carries required/optional, accepted dtypes and the role description.
 *  Keeps each binding row scannable instead of a verbose inline label. */
function roleBindingLabel(
  role: string,
  dtypes: string[],
  description: string,
  required: boolean,
): React.ReactNode {
  return (
    <Text
      span
      size="sm"
      fw={500}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
    >
      {role}
      {required ? (
        <Text span size="xs" c={REQUIRED_COLOR}>
          *
        </Text>
      ) : null}
      <Tooltip
        withinPortal
        multiline
        w={260}
        label={
          <Stack gap={2}>
            <Text size="xs" fw={600} c={required ? REQUIRED_COLOR : OPTIONAL_COLOR}>
              {required ? 'Required' : 'Optional'}
            </Text>
            {description ? <Text size="xs">{description}</Text> : null}
            <Text size="xs" c="dimmed">
              {dtypes.length ? `Accepts: ${dtypes.join(', ')}` : 'Accepts: any column'}
            </Text>
          </Stack>
        }
      >
        <Text span c="dimmed" style={{ display: 'inline-flex', cursor: 'help' }}>
          <Icon icon="mdi:information-outline" width={14} height={14} />
        </Text>
      </Tooltip>
    </Text>
  );
}

/** One row of the "Bindings overview" table: role name + a colour-coded
 *  required/optional badge, a simplified type, and the role description. */
function exampleInputRow(
  role: string,
  typeLabel: string,
  description: string,
  required: boolean,
): React.ReactNode {
  return (
    <Table.Tr key={`${required ? 'req' : 'opt'}-${role}`}>
      {/* Role + Type never wrap, so they always fit their content; Description
          is the only wrapping column and absorbs the remaining width. */}
      <Table.Td style={{ whiteSpace: 'nowrap', width: '1%' }}>
        <Group gap={6} wrap="nowrap">
          <Text size="xs" fw={500}>
            {role}
          </Text>
          <Badge size="xs" variant="light" color={required ? REQUIRED_COLOR : OPTIONAL_COLOR}>
            {required ? 'required' : 'optional'}
          </Badge>
        </Group>
      </Table.Td>
      <Table.Td style={{ whiteSpace: 'nowrap', width: '1%' }}>{typeLabel}</Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {description || '—'}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

const AdvancedVizBuilder: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const wfId = useBuilderStore((s) => s.wfId);
  const config = useBuilderStore((s) => s.config) as {
    viz_kind?: AdvancedVizKind;
    column_mapping?: Record<string, string | string[]>;
    preset_config?: Record<string, unknown> | null;
    config?: Record<string, unknown> | null;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const setPreviewReady = useBuilderStore((s) => s.setPreviewReady);

  const [kinds, setKinds] = useState<AdvancedVizKindDescriptor[] | null>(null);
  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [kindsError, setKindsError] = useState<string | null>(null);
  // Graded fit scores for every viz kind against the bound DC, from the backend
  // suggestion engine. Drives the ranked picker + the binding pre-fill.
  const [suggestions, setSuggestions] = useState<VizKindSuggestion[] | null>(null);

  const [search, setSearch] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    fetchAdvancedVizKinds()
      .then((res) => {
        if (!cancelled) setKinds(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setKindsError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!dcId) {
      setSchema(null);
      setSchemaError(null);
      return;
    }
    let cancelled = false;
    setSchemaError(null);
    setSchema(null);
    fetchPolarsSchema(dcId)
      .then((res) => {
        if (!cancelled) setSchema(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSchemaError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  const selectedKind = config.viz_kind || null;

  // Fetch the backend's graded fit scores for the bound DC. Every kind is
  // scored; the picker ranks them and the binding step pre-fills from each
  // kind's ranked role_candidates. Failures are silent — the picker still
  // works, just without scores/pre-fill.
  useEffect(() => {
    if (!dcId) {
      setSuggestions(null);
      return;
    }
    let cancelled = false;
    fetchVizSuggestions(dcId)
      .then((res) => {
        if (!cancelled) setSuggestions(res.viz_kinds);
      })
      .catch(() => {
        if (!cancelled) setSuggestions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  // Backend is the single source of truth for per-role accepted dtypes — read
  // them off the kind descriptor instead of a duplicated TS table.
  const kindMap = useMemo(
    () => new Map((kinds ?? []).map((k) => [k.viz_kind, k] as const)),
    [kinds],
  );
  const scoreMap = useMemo(
    () => new Map((suggestions ?? []).map((s) => [s.viz_kind, s] as const)),
    [suggestions],
  );
  const descriptor = selectedKind ? (kindMap.get(selectedKind) ?? null) : null;
  // [role, acceptedDtypes, description][] for the selected kind, split required
  // vs optional. Description feeds each binding's rich tooltip.
  const requiredRoles = useMemo<[string, string[], string][]>(
    () =>
      descriptor
        ? Object.entries(descriptor.roles)
            .filter(([, spec]) => spec.required)
            .map(([role, spec]) => [role, spec.dtypes, spec.description ?? ''])
        : [],
    [descriptor],
  );
  const optionalRoles = useMemo<[string, string[], string][]>(
    () =>
      descriptor
        ? Object.entries(descriptor.roles)
            .filter(([, spec]) => !spec.required)
            .map(([role, spec]) => [role, spec.dtypes, spec.description ?? ''])
        : [],
    [descriptor],
  );

  const columnMapping = useMemo(
    () => (config.column_mapping || {}) as Record<string, string | string[]>,
    [config.column_mapping],
  );

  // Edit-mode unpack: when a saved component is loaded, derive the role map
  // from the persisted `config.config.<role>_col` (and `rank_cols` for the
  // sunburst special case).
  useEffect(() => {
    if (Object.keys(columnMapping).length > 0) return;
    const persistedConfig = (config as unknown as { config?: Record<string, unknown> })
      .config;
    if (!persistedConfig || typeof persistedConfig !== 'object') return;
    const recovered: Record<string, string | string[]> = {};
    for (const [k, v] of Object.entries(persistedConfig)) {
      if (k === 'rank_cols' && Array.isArray(v)) {
        recovered.ranks = v as string[];
      } else if (k === 'step_cols' && Array.isArray(v)) {
        recovered.steps = v as string[];
      } else if (k === 'index_column' && typeof v === 'string') {
        recovered.index = v;
      } else if ((k === 'value_columns' || k === 'row_annotation_cols') && Array.isArray(v)) {
        recovered[k] = v as string[];
      } else if (k === 'compute_method' && typeof v === 'string') {
        recovered.compute_method = v;
      } else if (k.endsWith('_col') && typeof v === 'string') {
        recovered[k.slice(0, -'_col'.length)] = v;
      }
    }
    if (Object.keys(recovered).length > 0) {
      patchConfig({ column_mapping: recovered });
    }
  }, [config, columnMapping, patchConfig]);

  // Embedding live vs precomputed: when the picked DC has no precomputed
  // dim_1/dim_2 columns but has a wide feature matrix, the renderer needs to
  // run dim-reduction live. The builder hides the dim_1/dim_2 pickers in that
  // case and exposes a compute_method Select instead.
  const embeddingMode: EmbeddingMode | null = useMemo(() => {
    if (selectedKind !== 'embedding' || !schema) return null;
    return detectEmbeddingMode(schema);
  }, [selectedKind, schema]);

  // Auto-suggest mappings on kind change, pre-filling each required role with
  // its best-named candidate from the backend's ranked role_candidates. For
  // embedding live-compute mode, sample_id is the only required column binding;
  // compute_method is a scalar config field that defaults to "pca".
  useEffect(() => {
    if (!selectedKind || !schema) return;
    if (Object.keys(columnMapping).length > 0) return;

    const candidates = scoreMap.get(selectedKind)?.role_candidates ?? {};
    const liveEmbeddingSuggest =
      selectedKind === 'embedding' && embeddingMode === 'live';
    const rolesToSuggest = liveEmbeddingSuggest
      ? requiredRoles.filter(([role]) => role === 'sample_id')
      : requiredRoles;

    const suggest: Record<string, string> = {};
    for (const [role] of rolesToSuggest) {
      const best = candidates[role]?.[0];
      if (best) suggest[role] = best;
    }
    if (liveEmbeddingSuggest) {
      // Default the compute method to PCA; user can change in the dropdown.
      suggest.compute_method = 'pca';
    }
    if (Object.keys(suggest).length > 0) {
      patchConfig({ column_mapping: { ...columnMapping, ...suggest } });
    }
  }, [selectedKind, schema, columnMapping, patchConfig, embeddingMode, requiredRoles, scoreMap]);

  const setKind = (kind: AdvancedVizKind | null) => {
    // Re-picking a kind invalidates the catalog/saved preset (its control
    // extras belonged to the previous kind), so drop it.
    patchConfig({ viz_kind: kind || undefined, column_mapping: {}, preset_config: null });
  };

  const setRole = (role: string, value: string | string[] | null) => {
    const next: Record<string, string | string[]> = { ...columnMapping };
    if (value == null || (Array.isArray(value) && value.length === 0)) {
      delete next[role];
    } else {
      next[role] = value;
    }
    patchConfig({ column_mapping: next });
  };

  // In embedding live-compute mode the renderer ignores dim_1/dim_2 (the
  // Celery task derives them), so only sample_id is required from the DC.
  const liveEmbedding = selectedKind === 'embedding' && embeddingMode === 'live';

  // Tolerant validation. A missing required role or a wholly-incompatible
  // dtype is a blocking error; a castable-but-inexact dtype (e.g. Int for a
  // Float role) is a non-blocking warning the renderer can coerce. Save is
  // gated on errors only — warnings let the user proceed.
  const validation = useMemo(() => {
    if (!selectedKind || !schema) return { errors: [], warnings: [], ok: false };
    const errors: string[] = [];
    const warnings: string[] = [];
    const checkBinding = (role: string, accepted: string[], optional: boolean) => {
      const val = columnMapping[role];
      const prefix = optional ? 'Optional column' : 'Column';
      if (!val) {
        if (!optional) errors.push(`Required role "${role}" is not bound`);
        return;
      }
      const cols = Array.isArray(val) ? val : [val];
      for (const col of cols) {
        const dtype = schema[col];
        if (!dtype) {
          errors.push(`${prefix} "${col}" (role "${role}") is not in the DC`);
          continue;
        }
        const match = dtypeMatch(dtype, accepted);
        if (match === 'none') {
          errors.push(
            `${prefix} "${col}" (role "${role}") has dtype ${dtype}; expected one of ${accepted.join(', ')}`,
          );
        } else if (match === 'castable') {
          warnings.push(
            `${prefix} "${col}" (role "${role}") is ${dtype}; it will be coerced to ${accepted.join('/')}.`,
          );
        }
      }
    };
    for (const [role, accepted] of requiredRoles) {
      // In embedding live-compute mode the renderer derives dim_1/dim_2.
      if (liveEmbedding && (role === 'dim_1' || role === 'dim_2')) continue;
      checkBinding(role, accepted, false);
    }
    // Sunburst: rank_cols must have at least 2 columns.
    if (selectedKind === 'sunburst') {
      const ranks = columnMapping.ranks;
      if (!Array.isArray(ranks) || ranks.length < 2) {
        errors.push('Sunburst needs at least 2 rank columns');
      }
    }
    // Sankey: step_cols must have at least 2 ordered categorical columns.
    if (selectedKind === 'sankey') {
      const steps = columnMapping.steps;
      if (!Array.isArray(steps) || steps.length < 2) {
        errors.push('Sankey needs at least 2 step columns');
      }
    }
    for (const [role, accepted] of optionalRoles) {
      checkBinding(role, accepted, true);
    }
    if (liveEmbedding && !columnMapping.compute_method) {
      errors.push('Pick a compute method (PCA / UMAP / t-SNE / PCoA)');
    }
    return { errors, warnings, ok: errors.length === 0 };
  }, [selectedKind, schema, columnMapping, liveEmbedding, requiredRoles, optionalRoles]);

  const setSaveError = useBuilderStore((s) => s.setSaveError);
  useEffect(() => {
    if (!selectedKind) {
      setSaveError('Pick a viz kind to continue.');
      return;
    }
    if (!schema) {
      setSaveError(schemaError || 'Loading DC schema…');
      return;
    }
    setSaveError(validation.ok ? null : validation.errors.join(' • '));
  }, [selectedKind, schema, schemaError, validation, setSaveError]);

  // Dropdown options for a role: dtype-exact columns first, then castable ones
  // (flagged), so the tolerant binding can still offer an Int column for a
  // Float role without hiding it.
  const columnOptions = (accepted: string[]): { value: string; label: string }[] => {
    if (!schema) return [];
    const exact: { value: string; label: string }[] = [];
    const castable: { value: string; label: string }[] = [];
    for (const [name, dtype] of Object.entries(schema)) {
      const match = dtypeMatch(dtype, accepted);
      if (match === 'exact') exact.push({ value: name, label: `${name} : ${dtype}` });
      else if (match === 'castable')
        castable.push({ value: name, label: `${name} : ${dtype} (castable)` });
    }
    return [...exact, ...castable];
  };

  const allColumnOptions = (): { value: string; label: string }[] => {
    if (!schema) return [];
    return Object.entries(schema).map(([name, dtype]) => ({
      value: name,
      label: `${name} : ${dtype}`,
    }));
  };

  // Filter by free-text only; compatibility partitions are handled below.
  const matchedKinds = useMemo(() => {
    if (!kinds) return [];
    const q = search.trim().toLowerCase();
    if (!q) return kinds;
    return kinds.filter(
      (k) => k.label.toLowerCase().includes(q) || k.description.toLowerCase().includes(q),
    );
  }, [kinds, search]);

  // Rank every kind by the backend fit score. Nothing is hidden or disabled —
  // strong matches surface under "Recommended", the rest under "Other
  // visualisations", all fully selectable ("suggest but tolerate"). Until
  // scores arrive (no DC bound / still loading) we show one flat list.
  type RankedKind = { k: AdvancedVizKindDescriptor; suggestion?: VizKindSuggestion };
  const { recommendedKinds, otherKinds } = useMemo(() => {
    const decorated: RankedKind[] = matchedKinds.map((k) => ({
      k,
      suggestion: scoreMap.get(k.viz_kind),
    }));
    const scoreOf = (d: RankedKind) => d.suggestion?.score ?? -1;
    decorated.sort((a, b) => scoreOf(b) - scoreOf(a) || a.k.label.localeCompare(b.k.label));
    if (suggestions == null) return { recommendedKinds: [], otherKinds: decorated };
    const rec = decorated.filter((d) => (d.suggestion?.score ?? 0) >= RECOMMENDED_SCORE);
    const rest = decorated.filter((d) => (d.suggestion?.score ?? 0) < RECOMMENDED_SCORE);
    return { recommendedKinds: rec, otherKinds: rest };
  }, [matchedKinds, scoreMap, suggestions]);

  /** Render a titled grid of kind tiles with a fit-score badge. Tiles are
   *  always selectable; a tooltip surfaces which roles are missing/weak. */
  const renderKindSection = (
    title: string | null,
    items: RankedKind[],
  ): React.ReactNode => {
    if (items.length === 0) return null;
    return (
      <Stack gap={6}>
        {title ? <Text fw={600} size="sm">{title}</Text> : null}
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }} spacing="sm">
          {items.map(({ k, suggestion }) => {
            const isSelected = selectedKind === k.viz_kind;
            const fitPct = suggestion ? Math.round(suggestion.score * 100) : null;
            const gaps: string[] = [];
            if (suggestion?.unmet_roles?.length)
              gaps.push(`missing: ${suggestion.unmet_roles.join(', ')}`);
            if (suggestion?.weak_roles?.length)
              gaps.push(`weak match: ${suggestion.weak_roles.join(', ')}`);
            const tooltip = gaps.length ? gaps.join(' · ') : null;
            const tile = (
              <Paper
                withBorder
                p="sm"
                radius="md"
                onClick={() => setKind(k.viz_kind)}
                style={{
                  cursor: 'pointer',
                  borderColor: isSelected ? 'var(--mantine-color-pink-6)' : undefined,
                  background: isSelected ? 'var(--mantine-color-pink-0)' : undefined,
                  transition: 'transform 120ms ease, box-shadow 120ms ease',
                  transform: isSelected ? 'translateY(-1px)' : undefined,
                }}
              >
                <Stack gap={6}>
                  <Group gap={6} wrap="nowrap" justify="space-between">
                    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                      <Icon icon={k.icon} width={18} height={18} />
                      <Text fw={600} size="sm" lineClamp={1}>{k.label}</Text>
                    </Group>
                    {fitPct != null ? (
                      <Badge
                        size="xs"
                        variant="light"
                        color={fitPct >= RECOMMENDED_SCORE * 100 ? 'teal' : 'gray'}
                      >
                        {fitPct}% fit
                      </Badge>
                    ) : null}
                  </Group>
                  <Text size="xs" c="dimmed" lineClamp={3}>{k.description}</Text>
                  {isSelected ? <Badge size="xs" color="pink">selected</Badge> : null}
                </Stack>
              </Paper>
            );
            return (
              <div key={k.viz_kind}>
                {tooltip ? (
                  <Tooltip label={tooltip} multiline w={260} withinPortal>
                    {tile}
                  </Tooltip>
                ) : (
                  tile
                )}
              </div>
            );
          })}
        </SimpleGrid>
      </Stack>
    );
  };

  return (
    <Stack gap="md">
      <Title order={4}>Advanced visualisation</Title>
      <Text size="sm" c="dimmed">
        Each visualization is ranked by how well it fits this data collection.
        The recommended ones are the strongest matches — but you can pick any
        kind and bind the columns yourself.
      </Text>

      {kindsError ? (
        <Alert color="red" title="Failed to load viz kinds">
          {kindsError}
        </Alert>
      ) : null}

      <TextInput
        size="xs"
        placeholder="Filter by name / description…"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        style={{ maxWidth: 320 }}
      />

      {renderKindSection(
        recommendedKinds.length ? 'Recommended for this data collection' : null,
        recommendedKinds,
      )}
      {renderKindSection(
        recommendedKinds.length ? 'Other visualisations' : 'Visualisations',
        otherKinds,
      )}

      {selectedKind ? (
        <Paper withBorder p="md" radius="md">
          <Stack gap="xs">
            <Text fw={600}>Column bindings</Text>
            <Paper withBorder p="xs" radius="sm">
              <Stack gap={4}>
                <Text size="xs" fw={500}>Bindings overview</Text>
                <Text size="xs" c="dimmed">
                  The roles this visualization binds. Hover a binding below for full details.
                </Text>
                <Table withTableBorder withColumnBorders striped fz="xs" layout="auto">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th style={{ whiteSpace: 'nowrap', width: '1%' }}>Role</Table.Th>
                      <Table.Th style={{ whiteSpace: 'nowrap', width: '1%' }}>Type</Table.Th>
                      <Table.Th>Description</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {requiredRoles
                      .filter(
                        ([role]) =>
                          !liveEmbedding || (role !== 'dim_1' && role !== 'dim_2'),
                      )
                      .map(([role, accepted, description]) =>
                        exampleInputRow(role, simplifyDtypes(accepted), description, true),
                      )}
                    {selectedKind === 'sunburst'
                      ? exampleInputRow(
                          'ranks',
                          'any (≥2, ordered)',
                          'Hierarchy columns from root to leaf.',
                          true,
                        )
                      : null}
                    {selectedKind === 'sankey'
                      ? exampleInputRow(
                          'step columns',
                          'any (≥2, ordered)',
                          'Ordered categorical levels the flow passes through.',
                          true,
                        )
                      : null}
                    {liveEmbedding
                      ? exampleInputRow(
                          'compute_method',
                          'choice',
                          'Dimensionality reduction: pca / umap / tsne / pcoa.',
                          true,
                        )
                      : null}
                    {optionalRoles.map(([role, accepted, description]) =>
                      exampleInputRow(role, simplifyDtypes(accepted), description, false),
                    )}
                  </Table.Tbody>
                </Table>
              </Stack>
            </Paper>
            <Divider />
            {schemaError ? (
              <Alert color="red" title="Failed to load DC schema">
                {schemaError}
              </Alert>
            ) : !dcId ? (
              <Alert color="yellow">Pick a data collection in step 1 first.</Alert>
            ) : !schema ? (
              <Text size="sm" c="dimmed">Loading DC schema…</Text>
            ) : (
              <>
                {/* Sunburst has a multi-column "ranks" binding alongside its
                    single-column abundance role; render the MultiSelect when
                    the kind supports a list binding. */}
                {selectedKind === 'sunburst' ? (
                  <MultiSelect
                    label={roleBindingLabel(
                      'ranks',
                      [],
                      'Hierarchy columns from root to leaf — pick at least 2, in order.',
                      true,
                    )}
                    placeholder="Pick rank columns in order"
                    value={
                      Array.isArray(columnMapping.ranks)
                        ? (columnMapping.ranks as string[])
                        : []
                    }
                    onChange={(v) => setRole('ranks', v)}
                    data={allColumnOptions()}
                    searchable
                    clearable
                  />
                ) : null}
                {/* Sankey has no single <role>_col schema — it binds an ordered
                    list of categorical columns (step_cols). Without this block
                    the kind was selectable but unbindable, so the renderer
                    failed with "≥2 step columns required". */}
                {selectedKind === 'sankey' ? (
                  <MultiSelect
                    label={roleBindingLabel(
                      'step columns',
                      [],
                      'Ordered categorical levels the flow passes through (e.g. sample → lineage → clade). Pick at least 2, in order.',
                      true,
                    )}
                    placeholder="Pick step columns in order"
                    value={
                      Array.isArray(columnMapping.steps)
                        ? (columnMapping.steps as string[])
                        : []
                    }
                    onChange={(v) => setRole('steps', v)}
                    data={allColumnOptions()}
                    searchable
                    clearable
                  />
                ) : null}
                {/* ComplexHeatmap: beyond the index row-id, let the user choose
                    which numeric columns form the matrix (excluding the rest)
                    and which categorical columns annotate the rows. */}
                {selectedKind === 'complex_heatmap' ? (
                  <>
                    <MultiSelect
                      label={roleBindingLabel(
                        'value columns',
                        NUMERIC_ANY,
                        'Numeric columns that form the heatmap matrix. Leave empty to use every numeric column; pick a subset to exclude the rest.',
                        false,
                      )}
                      placeholder="All numeric columns (pick to restrict / exclude)"
                      value={
                        Array.isArray(columnMapping.value_columns)
                          ? (columnMapping.value_columns as string[])
                          : []
                      }
                      onChange={(v) => setRole('value_columns', v)}
                      data={columnOptions(NUMERIC_ANY)}
                      searchable
                      clearable
                    />
                    <MultiSelect
                      label={roleBindingLabel(
                        'row annotation columns',
                        STRING_LIKE,
                        'Categorical columns drawn as a colour strip beside the rows (e.g. Kingdom / taxonomy level). Excluded from the matrix.',
                        false,
                      )}
                      placeholder="Pick categorical columns to annotate rows"
                      value={
                        Array.isArray(columnMapping.row_annotation_cols)
                          ? (columnMapping.row_annotation_cols as string[])
                          : []
                      }
                      onChange={(v) => setRole('row_annotation_cols', v)}
                      data={columnOptions(STRING_LIKE)}
                      searchable
                      clearable
                    />
                  </>
                ) : null}
                {/* Embedding live-compute mode: surface compute_method Select
                    in place of dim_1/dim_2 pickers. Renderer dispatches the
                    chosen reduction as a Celery task. */}
                {liveEmbedding ? (
                  <>
                    <Alert color="teal" variant="light">
                      <Text size="xs">
                        Live-compute mode: the renderer will run the chosen
                        dim-reduction on this DC's feature columns via Celery.
                      </Text>
                    </Alert>
                    <Select
                      label="compute method (required)"
                      placeholder="Pick a dim-reduction"
                      value={
                        typeof columnMapping.compute_method === 'string'
                          ? (columnMapping.compute_method as string)
                          : null
                      }
                      onChange={(v) => setRole('compute_method', v)}
                      data={[
                        { value: 'pca', label: 'PCA' },
                        { value: 'umap', label: 'UMAP' },
                        { value: 'tsne', label: 't-SNE' },
                        { value: 'pcoa', label: 'PCoA (Bray–Curtis)' },
                      ]}
                    />
                  </>
                ) : null}
                {requiredRoles
                  .filter(
                    // Skip dim_1/dim_2 when running embedding live — the
                    // Celery task derives them.
                    ([role]) =>
                      !liveEmbedding || (role !== 'dim_1' && role !== 'dim_2'),
                  )
                  .map(([role, accepted, description]) => (
                  <Select
                    key={role}
                    label={roleBindingLabel(role, accepted, description, true)}
                    placeholder="Pick a column"
                    value={
                      typeof columnMapping[role] === 'string'
                        ? (columnMapping[role] as string)
                        : null
                    }
                    onChange={(v) => setRole(role, v)}
                    data={columnOptions(accepted)}
                    searchable
                    clearable
                    nothingFoundMessage="No column with a compatible dtype"
                  />
                ))}
                {optionalRoles.map(([role, accepted, description]) => (
                  <Select
                    key={role}
                    label={roleBindingLabel(role, accepted, description, false)}
                    placeholder="Pick a column"
                    value={
                      typeof columnMapping[role] === 'string'
                        ? (columnMapping[role] as string)
                        : null
                    }
                    onChange={(v) => setRole(role, v)}
                    data={columnOptions(accepted)}
                    searchable
                    clearable
                    nothingFoundMessage="No column with a compatible dtype"
                  />
                ))}
                {!validation.ok ? (
                  <Alert color="orange" title="Bindings incomplete or invalid">
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {validation.errors.map((e) => (
                        <li key={e}>
                          <Text size="xs">{e}</Text>
                        </li>
                      ))}
                    </ul>
                  </Alert>
                ) : null}
                {validation.warnings.length > 0 ? (
                  <Alert color="yellow" variant="light" title="Heads up — dtype coercion">
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {validation.warnings.map((w) => (
                        <li key={w}>
                          <Text size="xs">{w}</Text>
                        </li>
                      ))}
                    </ul>
                  </Alert>
                ) : null}
              </>
            )}
          </Stack>
        </Paper>
      ) : null}

      {selectedKind && wfId && dcId ? (
        <AdvancedVizPreview
          vizKind={selectedKind}
          columnMapping={columnMapping}
          wfId={wfId}
          dcId={dcId}
          bindingsValid={validation.ok}
          onReady={setPreviewReady}
          presetConfig={config.preset_config ?? config.config ?? null}
        />
      ) : null}
    </Stack>
  );
};

export default AdvancedVizBuilder;

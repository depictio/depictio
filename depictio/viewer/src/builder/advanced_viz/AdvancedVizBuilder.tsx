/**
 * Builder for the advanced_viz component family.
 *
 * Two-step inside the per-type panel:
 *   1) Pick viz_kind. The backend's suggestion engine ranks every kind for
 *      the bound DC (and the dashboard tab it lands on); the picker surfaces
 *      the strong matches under "Recommended" and the rest under "Other
 *      visualisations". Each tile shows what the ranking rests on (a named,
 *      shape or selection match, or weak) with the reasons in a tooltip; the
 *      numeric score only orders the tiles. Nothing is hidden or disabled:
 *      the user can pick any kind and bind columns manually ("suggest but
 *      tolerate").
 *   2) Bind each required role to a column from the chosen DC. Accepted dtypes
 *      and the candidate pre-fill both come from the backend (single source of
 *      truth — see /advanced_viz/kinds and /datacollections/viz-suggestions),
 *      so the TS side never duplicates the schema. A castable-but-inexact dtype
 *      (e.g. Int for a Float role) is a tolerant warning, not a blocker.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Collapse,
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
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  AdvancedVizKind,
  AdvancedVizKindDescriptor,
  VizKindSuggestion,
  VizSuggestionContext,
  fetchAdvancedVizKinds,
  fetchDashboard,
  fetchPolarsSchema,
  fetchVizSuggestions,
} from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import DesignShell from '../shared/DesignShell';
import PreviewPanel from '../shared/PreviewPanel';
import AdvancedVizPreview from './AdvancedVizPreview';
import { mergedPresetConfig, rolesFromConfigBlob } from './configBlob';
import {
  RankedKind,
  matchBadge,
  partitionKinds,
  suggestionContextFor,
  suggestionTooltip,
} from './kindPicker';
import RecordCardLinkSettings from './RecordCardLinkSettings';

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

/** A titled block that starts collapsed.
 *
 *  Both places this is used are reference material rather than the next thing
 *  to do: the long tail of visualisation kinds once the recommended ones are
 *  on screen, and the binding table once every required role already has a
 *  column (which is always the case when the component came from the
 *  catalog). Collapsed they cost one line each; the header keeps them
 *  discoverable, and the count says what is inside.
 *
 *  Module scope on purpose: declared inside the builder it would be a fresh
 *  component type on every render, so React would remount it and snap it shut
 *  the moment anything else changed - picking a kind, typing a filter, binding
 *  a column.
 *
 *  `forceOpen` overrides the collapsed state without consuming it: a filter
 *  that leaves its own matches hidden behind a closed section reads as a broken
 *  filter, and the section returns to whatever the user left it on once the
 *  filter clears. */
const Disclosure: React.FC<{
  title: string;
  count?: number;
  defaultOpen?: boolean;
  forceOpen?: boolean;
  children: React.ReactNode;
}> = ({ title, count, defaultOpen = false, forceOpen = false, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  const shown = open || forceOpen;
  return (
    <Stack gap={6}>
      <UnstyledButton onClick={() => setOpen(!shown)} aria-expanded={shown}>
        <Group gap={6} wrap="nowrap">
          <Icon
            icon={shown ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            width={16}
            color="var(--mantine-color-dimmed)"
          />
          <Text fw={600} size="sm">{title}</Text>
          {count != null && (
            <Badge size="xs" variant="light" color="gray" radius="sm">{count}</Badge>
          )}
        </Group>
      </UnstyledButton>
      <Collapse in={shown}>{children}</Collapse>
    </Stack>
  );
};


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

/** One row of the "Bindings overview" table: role name, a simplified type, a
 *  colour-coded required/optional column, and the role description. */
function exampleInputRow(
  role: string,
  typeLabel: string,
  description: string,
  required: boolean,
): React.ReactNode {
  return (
    <Table.Tr key={`${required ? 'req' : 'opt'}-${role}`}>
      {/* Role, Type + Required never wrap, so they always fit their content;
          Description is the only wrapping column and absorbs the remaining width. */}
      <Table.Td style={{ whiteSpace: 'nowrap', width: '1%' }}>
        <Text size="xs" fw={500}>
          {role}
        </Text>
      </Table.Td>
      <Table.Td style={{ whiteSpace: 'nowrap', width: '1%' }}>{typeLabel}</Table.Td>
      <Table.Td style={{ whiteSpace: 'nowrap', width: '96px' }}>
        <Badge size="xs" variant="light" color={required ? REQUIRED_COLOR : OPTIONAL_COLOR}>
          {required ? 'required' : 'optional'}
        </Badge>
      </Table.Td>
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
    viz_overrides?: Record<string, unknown> | null;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const mode = useBuilderStore((s) => s.mode);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const componentId = useBuilderStore((s) => s.componentId);
  const setPreviewReady = useBuilderStore((s) => s.setPreviewReady);

  // Tier-2 edits made in the preview's own settings popover.
  //
  // Read through getState() rather than the subscribed `config` so this keeps a
  // single identity for the life of the builder: it ends up as a context value
  // in the preview, and an unstable one would re-render the whole preview
  // subtree on every keystroke in a binding Select.
  //
  // Written synchronously, never debounced: handleDirectAdd in CatalogTab reads
  // the store immediately after seeding it, so a deferred write would be a race
  // that loses the author's last edit on a fast Save.
  const setVizOverride = useCallback(
    (patch: Record<string, unknown>) => {
      const current = (useBuilderStore.getState().config as { viz_overrides?: Record<string, unknown> | null })
        .viz_overrides ?? {};
      patchConfig({ viz_overrides: { ...current, ...patch } });
    },
    [patchConfig],
  );

  // Record-card link fields. Same override layer as above, except that
  // `undefined` means "unset": the key is dropped when the saved config never
  // had it, and nulled when it did, so clearing a link neither leaves the old
  // one in place nor writes a key the saved component did not carry.
  const setRecordCardFields = useCallback(
    (patch: Record<string, unknown>) => {
      const c = useBuilderStore.getState().config as {
        preset_config?: Record<string, unknown> | null;
        config?: Record<string, unknown> | null;
        viz_overrides?: Record<string, unknown> | null;
      };
      const inherited = c.preset_config ?? c.config ?? {};
      const next: Record<string, unknown> = { ...(c.viz_overrides ?? {}) };
      for (const [key, value] of Object.entries(patch)) {
        if (value !== undefined) next[key] = value;
        else if (inherited[key] != null) next[key] = null;
        else delete next[key];
      }
      patchConfig({ viz_overrides: next });
    },
    [patchConfig],
  );

  const [kinds, setKinds] = useState<AdvancedVizKindDescriptor[] | null>(null);
  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [kindsError, setKindsError] = useState<string | null>(null);
  // Graded fit scores for every viz kind against the bound DC, from the backend
  // suggestion engine. Drives the ranked picker + the binding pre-fill.
  const [suggestions, setSuggestions] = useState<VizKindSuggestion[] | null>(null);
  // The dashboard tab the tile lands on, as the suggestion engine reads it
  // (selection columns, kinds already there). `undefined` while it loads, so
  // the picker is ranked once with the context rather than twice.
  const [tabContext, setTabContext] = useState<VizSuggestionContext | null | undefined>(
    dashboardId ? undefined : null,
  );

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

  useEffect(() => {
    if (!dashboardId) {
      setTabContext(null);
      return;
    }
    let cancelled = false;
    setTabContext(undefined);
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (!cancelled) {
          setTabContext(suggestionContextFor(dash.stored_metadata ?? [], componentId));
        }
      })
      .catch(() => {
        if (!cancelled) setTabContext(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, componentId]);

  // Fetch the backend's suggestions for the bound DC. Every kind is scored;
  // the picker ranks them and the binding step pre-fills from each kind's
  // ranked role_candidates. Failures are silent: the picker still works,
  // just without ranking/pre-fill.
  useEffect(() => {
    if (!dcId) {
      setSuggestions(null);
      return;
    }
    if (tabContext === undefined) return;
    let cancelled = false;
    fetchVizSuggestions(dcId, tabContext ?? undefined)
      .then((res) => {
        if (!cancelled) setSuggestions(res.viz_kinds);
      })
      .catch(() => {
        if (!cancelled) setSuggestions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, tabContext]);

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

  // The preview must render exactly what Save will persist, so both go through
  // the one merge helper rather than each spelling the layering out.
  const mergedPreset = useMemo(
    () => mergedPresetConfig(config),
    [config.preset_config, config.config, config.viz_overrides],
  );

  // Unpack a config blob back into the role map: a saved component being edited
  // (`config.config`) or a catalog offer's grounded preset (`preset_config`).
  // `rolesFromConfigBlob` is the inverse of the mapping the save path applies,
  // so the two directions live together and cannot drift.
  //
  // Fills in only the roles the mapping is *missing*, rather than bailing as
  // soon as it holds anything. A catalog offer arrives with its declared roles
  // already set, while the binding it had no way to declare lives only in the
  // preset: a sunburst declares `abundance` and has its rank hierarchy inferred
  // server-side. Bailing on the non-empty mapping is what made an offer that
  // previews correctly report "needs at least 2 rank columns" once opened.
  //
  // Seeded once per blob, tracked by identity rather than by diffing against
  // the current mapping on every render. The blob never changes, so a re-diff
  // would treat a role the user had just cleared as "missing" and put it
  // straight back, making an optional binding impossible to unbind.
  const seededBlob = useRef<object | null>(null);
  useEffect(() => {
    const blob = config.preset_config ?? config.config;
    if (!blob || typeof blob !== 'object') return;
    if (seededBlob.current === blob) return;
    seededBlob.current = blob;
    const recovered = rolesFromConfigBlob(selectedKind ?? undefined, blob);
    const missing = Object.fromEntries(
      Object.entries(recovered).filter(([role]) => !(role in columnMapping)),
    );
    if (Object.keys(missing).length > 0) {
      patchConfig({ column_mapping: { ...columnMapping, ...missing } });
    }
  }, [config, columnMapping, patchConfig, selectedKind]);

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

    // Each role takes its best candidate not already taken, so an x/y pair
    // never pre-fills with the same column twice.
    const suggest: Record<string, string> = {};
    const taken = new Set<string>();
    for (const [role] of rolesToSuggest) {
      const ranked = candidates[role] ?? [];
      const best = ranked.find((c) => !taken.has(c)) ?? ranked[0];
      if (best) {
        suggest[role] = best;
        taken.add(best);
      }
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
    // The overrides go with it: `top_n` means something on a taxonomy bar and
    // nothing on a volcano, and a foreign key would be rejected outright by the
    // new kind's config model.
    //
    // `config` is the blob of the component being edited, and it goes too. The
    // role-recovery effect below falls back to it, and its `<role>_col` keys
    // carry no record of which kind they came from, so a Manhattan edited into
    // a Volcano would otherwise inherit chromosome/position/score bindings and
    // save a config the Volcano model rejects outright.
    patchConfig({
      viz_kind: kind || undefined,
      column_mapping: {},
      preset_config: null,
      viz_overrides: null,
      config: null,
    });
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

  // The component's own kind is pinned on its own; everything else is ranked
  // by the backend fit score. Nothing is hidden or disabled: strong matches
  // surface under "Recommended", the rest under "Other visualisations", all
  // fully selectable ("suggest but tolerate"). See `partitionKinds` for why
  // the current kind is kept out of the ranking.
  const {
    current: currentKind,
    recommended: recommendedKinds,
    other: otherKinds,
  } = useMemo(
    () => partitionKinds(kinds, suggestions, selectedKind, search),
    [kinds, suggestions, selectedKind, search],
  );

  // Every required role already has a column — which is the state a component
  // arrives in when it came from the catalog, and the state a manual build ends
  // in. Nothing left to do here, so the bindings block starts collapsed.
  const allRequiredBound = useMemo(
    () =>
      requiredRoles.length > 0 &&
      requiredRoles.every(([role]) => {
        const v = columnMapping[role];
        return Array.isArray(v) ? v.length > 0 : Boolean(v);
      }),
    [requiredRoles, columnMapping],
  );

  /** Render a titled grid of kind tiles with a match badge (named, shape,
   *  selection, weak). Tiles are always selectable; a tooltip lists the
   *  reasons behind the match and any role the collection cannot fill. */
  const renderKindSection = (
    title: string | null,
    items: RankedKind[],
  ): React.ReactNode => {
    if (items.length === 0) return null;
    return (
      <Stack gap={6}>
        {title ? <Text fw={600} size="sm">{title}</Text> : null}
        {/* Viewport breakpoints, left-column widths: full width below md (the
            shell stacks), a ~10/24 column above it, so two tiles is the most
            that stays readable and md, the narrowest column, takes one. */}
        <SimpleGrid cols={{ base: 1, sm: 2, md: 1, lg: 2 }} spacing="sm">
          {items.map(({ k, suggestion }) => {
            const isSelected = selectedKind === k.viz_kind;
            const badge = matchBadge(suggestion);
            const tooltipLines = suggestionTooltip(suggestion);
            const tooltip = tooltipLines.length ? (
              <Stack gap={2}>
                {tooltipLines.map((line) => (
                  <div key={line}>{line}</div>
                ))}
              </Stack>
            ) : null;
            const tile = (
              <Paper
                withBorder
                p="sm"
                radius="md"
                // Re-picking the kind already bound would run setKind's reset
                // and wipe the saved bindings for nothing.
                onClick={() => {
                  if (!isSelected) setKind(k.viz_kind);
                }}
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
                    {badge ? (
                      <Badge size="xs" variant="light" color={badge.color} style={{ flexShrink: 0 }}>
                        {badge.label}
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

  const kindPicker = (
    <Stack gap="md">
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
      {recommendedKinds.length ? (
        otherKinds.length > 0 && (
          <Disclosure
            title="Other visualisations"
            count={otherKinds.length}
            forceOpen={Boolean(search.trim())}
          >
            {renderKindSection(null, otherKinds)}
          </Disclosure>
        )
      ) : (
        renderKindSection(currentKind ? 'Other visualisations' : 'Visualisations', otherKinds)
      )}
    </Stack>
  );

  const form = (
    <Stack gap="md">
      <Title order={4}>Advanced visualisation</Title>
      <Text size="sm" c="dimmed">
        {currentKind
          ? 'The visualisation this component uses comes first. The others are ranked by how well they fit this data collection, and picking one rebinds the component from scratch.'
          : 'Each visualization is ranked by how well it fits this data collection. The recommended ones are the strongest matches, but you can pick any kind and bind the columns yourself.'}
      </Text>

      {kindsError ? (
        <Alert color="red" title="Failed to load viz kinds">
          {kindsError}
        </Alert>
      ) : null}

      {currentKind ? renderKindSection('Current visualisation', [currentKind]) : null}
      {selectedKind && !currentKind && kinds ? (
        <Alert color="yellow" variant="light">
          <Text size="xs">
            This component uses "{selectedKind}", which is not a known visualisation
            kind. Pick one below to rebind it.
          </Text>
        </Alert>
      ) : null}

      {/* Editing an existing component: the kind is already chosen, so the
          catalogue of alternatives is reference material and starts collapsed.
          Creating one: the picker is the next thing to do and stays open. */}
      {mode === 'edit' && currentKind ? (
        <Disclosure
          title="Change visualisation"
          count={recommendedKinds.length + otherKinds.length}
          forceOpen={Boolean(search.trim())}
        >
          {kindPicker}
        </Disclosure>
      ) : (
        kindPicker
      )}

      {selectedKind ? (
        <Paper withBorder p="md" radius="md">
          <Disclosure title="Column bindings" defaultOpen={!allRequiredBound}>
           <Stack gap="xs">
            <Paper withBorder p="xs" radius="sm">
              <Stack gap={4}>
                <Text size="xs" fw={500}>Roles reference</Text>
                <Text size="xs" c="dimmed">
                  The roles this visualization binds. Hover a binding below for full details.
                </Text>
                <Table withTableBorder withColumnBorders striped fz="xs" layout="auto">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th style={{ whiteSpace: 'nowrap', width: '1%' }}>Role</Table.Th>
                      <Table.Th style={{ whiteSpace: 'nowrap', width: '1%' }}>Type</Table.Th>
                      <Table.Th style={{ whiteSpace: 'nowrap', width: '96px' }}>Required</Table.Th>
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
          </Disclosure>
        </Paper>
      ) : null}

      {selectedKind === 'record_card' ? (
        <RecordCardLinkSettings
          config={mergedPreset}
          idCol={typeof columnMapping.id === 'string' ? columnMapping.id : null}
          onChange={setRecordCardFields}
        />
      ) : null}
    </Stack>
  );

  // Same two-panel shell as the other builders: every control on the left, the
  // live preview sticky on the right. Until a kind is picked (and a collection
  // bound) the right panel holds the shared empty state instead of nothing, so
  // the layout does not jump when the preview arrives.
  const preview =
    selectedKind && wfId && dcId ? (
      <AdvancedVizPreview
        vizKind={selectedKind}
        columnMapping={columnMapping}
        wfId={wfId}
        dcId={dcId}
        bindingsValid={validation.ok}
        onReady={setPreviewReady}
        presetConfig={mergedPreset}
        onVizControlChange={setVizOverride}
      />
    ) : (
      <PreviewPanel
        minHeight={520}
        empty
        emptyMessage={
          selectedKind
            ? 'Pick a data collection to see a live preview.'
            : 'Pick a visualisation on the left to see a live preview.'
        }
      />
    );

  return <DesignShell formSlot={form} previewSlot={preview} />;
};

export default AdvancedVizBuilder;

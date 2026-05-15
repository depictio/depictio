/**
 * Builder for the advanced_viz component family.
 *
 * Two-step inside the per-type panel:
 *   1) Pick viz_kind (gallery of tiles with description + domain badge; tiles
 *      whose required roles can't be satisfied by the bound DC are greyed-out
 *      with a tooltip explaining what's missing).
 *   2) Bind each required role to a column from the chosen DC, with
 *      editor-time validation against the DC's polars schema.
 *
 * Validation mirrors depictio/models/components/advanced_viz/schemas.py
 * (server side) so Save is only enabled once required roles are mapped to
 * existing columns of an acceptable dtype.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
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
  fetchAdvancedVizKinds,
  fetchPolarsSchema,
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

// Mirror of depictio/models/components/advanced_viz/schemas.py CANONICAL_SCHEMAS.
// Keep this in sync — drift causes the picker to either undergate (showing
// kinds the backend will reject at save) or overgate (hiding viable kinds).
const REQUIRED_ROLES: Record<AdvancedVizKind, Record<string, string[]>> = {
  volcano: {
    feature_id: STRING_LIKE,
    effect_size: NUMERIC_FLOAT,
    significance: NUMERIC_FLOAT,
  },
  embedding: {
    sample_id: STRING_LIKE,
    dim_1: NUMERIC_FLOAT,
    dim_2: NUMERIC_FLOAT,
  },
  manhattan: {
    chr: STRING_LIKE,
    pos: NUMERIC_INT,
    score: NUMERIC_FLOAT,
  },
  stacked_taxonomy: {
    sample_id: STRING_LIKE,
    taxon: STRING_LIKE,
    rank: STRING_LIKE,
    abundance: NUMERIC_ANY,
  },
  phylogenetic: {
    taxon: STRING_LIKE,
  },
  rarefaction: {
    sample_id: STRING_LIKE,
    depth: NUMERIC_ANY,
    metric: NUMERIC_ANY,
  },
  ancombc_differentials: {
    feature_id: STRING_LIKE,
    contrast: STRING_LIKE,
    lfc: NUMERIC_FLOAT,
    significance: NUMERIC_FLOAT,
  },
  da_barplot: {
    feature_id: STRING_LIKE,
    contrast: STRING_LIKE,
    lfc: NUMERIC_FLOAT,
  },
  enrichment: {
    term: STRING_LIKE,
    nes: NUMERIC_FLOAT,
    padj: NUMERIC_FLOAT,
    gene_count: NUMERIC_ANY,
  },
  complex_heatmap: {
    index: STRING_LIKE,
  },
  upset_plot: {},
  ma: {
    feature_id: STRING_LIKE,
    avg_log_intensity: NUMERIC_FLOAT,
    log2_fold_change: NUMERIC_FLOAT,
  },
  dot_plot: {
    cluster: STRING_LIKE,
    gene: STRING_LIKE,
    mean_expression: NUMERIC_FLOAT,
    frac_expressing: NUMERIC_FLOAT,
  },
  lollipop: {
    feature_id: STRING_LIKE,
    position: NUMERIC_INT,
    category: STRING_LIKE,
  },
  qq: {
    p_value: NUMERIC_FLOAT,
  },
  sunburst: {
    abundance: NUMERIC_ANY,
  },
  oncoplot: {
    sample_id: STRING_LIKE,
    gene: STRING_LIKE,
    mutation_type: STRING_LIKE,
  },
  coverage_track: {
    chromosome: STRING_LIKE,
    position: NUMERIC_INT,
    value: NUMERIC_ANY,
  },
  // Sankey's step_cols is a multi-column list — no single <role>_col role.
  // The builder enforces ≥2 columns via a separate `step_cols` UI block, the
  // same way Sunburst handles rank_cols.
  sankey: {},
};

const OPTIONAL_ROLES: Record<AdvancedVizKind, Record<string, string[]>> = {
  volcano: { label: STRING_LIKE, category: STRING_LIKE },
  embedding: {
    dim_3: NUMERIC_FLOAT,
    cluster: STRING_LIKE,
    color: [...NUMERIC_ANY, ...STRING_LIKE],
  },
  manhattan: { feature: STRING_LIKE, effect: NUMERIC_FLOAT },
  stacked_taxonomy: {},
  phylogenetic: {},
  rarefaction: { iter: NUMERIC_ANY, group: STRING_LIKE },
  ancombc_differentials: { label: STRING_LIKE },
  da_barplot: { significance: NUMERIC_FLOAT, label: STRING_LIKE },
  enrichment: { source: STRING_LIKE },
  complex_heatmap: {},
  upset_plot: {},
  ma: { significance: NUMERIC_FLOAT, label: STRING_LIKE },
  dot_plot: {},
  lollipop: { effect: NUMERIC_FLOAT },
  qq: { feature_id: STRING_LIKE, category: STRING_LIKE },
  sunburst: {},
  oncoplot: {},
  coverage_track: {
    end: NUMERIC_INT,
    sample: STRING_LIKE,
    category: STRING_LIKE,
  },
  sankey: {},
};

/** Canonical role → likely column-name aliases (lowercased). Reused by both
 *  the picker's compatibility check AND the auto-suggest binding logic, so
 *  there's one source of truth for "what columns this role can come from".
 *  Adding an alias here makes more DCs viable for the kind it appears in. */
const ROLE_ALIASES: Record<string, string[]> = {
  feature_id: ['feature_id', 'gene', 'id', 'feature', 'taxon'],
  effect_size: ['effect_size', 'lfc', 'log2foldchange', 'log2fc', 'effect'],
  significance: ['significance', 'padj', 'q_val', 'qvalue', 'pvalue', 'p_val', 'p_value'],
  sample_id: ['sample_id', 'sample', 'sampleid', 'sample_name'],
  dim_1: ['dim_1', 'pc1', 'umap1', 'tsne1'],
  dim_2: ['dim_2', 'pc2', 'umap2', 'tsne2'],
  chr: ['chr', 'chrom', 'chromosome'],
  pos: ['pos', 'position', 'start'],
  score: ['score', 'pvalue', 'p_val', 'qvalue', 'q_val', 'neg_log10_qval'],
  taxon: ['taxon', 'taxonomy', 'name'],
  rank: ['rank', 'level'],
  abundance: ['abundance', 'rel_abundance', 'count', 'value'],
  avg_log_intensity: ['avg_log_intensity', 'mean_intensity', 'basemean'],
  log2_fold_change: ['log2_fold_change', 'lfc', 'log2fc', 'effect_size'],
  cluster: ['cluster', 'cell_type', 'group'],
  gene: ['gene', 'feature_id', 'symbol'],
  mean_expression: ['mean_expression', 'expression', 'mean_expr'],
  frac_expressing: ['frac_expressing', 'pct_expressing', 'fraction'],
  position: ['position', 'pos', 'start'],
  category: ['category', 'consequence', 'type', 'pathway', 'label'],
  p_value: ['p_value', 'pvalue', 'p_val'],
  mutation_type: ['mutation_type', 'mutation', 'classification', 'variant_class'],
  iter: ['iter', 'iteration', 'depth', 'step'],
  label: ['label', 'name', 'category', 'contrast'],
  source: ['source', 'pathway', 'term', 'set'],
  effect: ['effect', 'effect_size', 'lfc'],
  feature: ['feature', 'feature_id', 'gene', 'id', 'name'],
  contrast: ['contrast', 'comparison', 'condition', 'group'],
  lfc: ['lfc', 'log2foldchange', 'log2_fold_change', 'log2fc', 'effect_size'],
  term: ['term', 'pathway', 'go_term', 'gene_set', 'set'],
  nes: ['nes', 'enrichment_score', 'es'],
  padj: ['padj', 'qvalue', 'q_val', 'p_adj', 'fdr'],
  gene_count: ['gene_count', 'set_size', 'size', 'n_genes', 'count'],
  index: ['index', 'feature_id', 'gene', 'id', 'name', 'row_id', 'sample_id', 'sample'],
  depth: ['depth', 'sample_depth', 'reads', 'subsample_depth'],
  metric: ['metric', 'shannon', 'faith_pd', 'observed_features', 'value'],
};

/** Extra gates beyond REQUIRED_ROLES — for kinds whose Pydantic config has a
 *  permissive single-role schema but whose renderer actually demands a wide
 *  Float matrix (ComplexHeatmap) or many binary set-membership columns
 *  (UpSet). The matrix-style kinds were passing the role check via
 *  name-aliasing alone (e.g. feature_id → index) while the runtime then
 *  errored. Float-only for heatmap because binary 0/1 indicator columns
 *  (Int) are UpSet-style data, not a continuous matrix for clustering —
 *  upset_demo was leaking through MIN_NUMERIC_COLS before this fix. */
const MIN_FLOAT_COLS: Partial<Record<AdvancedVizKind, number>> = {
  complex_heatmap: 4,
};
// UpSet's set-membership columns are 0/1 indicators — typed as Int by polars.
// Requiring ≥3 Int columns filters out DCs with only float measurements
// (volcano, embedding) while keeping legitimate upset_demo data.
const MIN_INT_COLS: Partial<Record<AdvancedVizKind, number>> = {
  upset_plot: 3,
};

/** Kinds that need a specific DC `config.type` regardless of column matching.
 *  Phylogenetic requires a phylogeny-type DC (the .nwk tree file); any Table
 *  DC with a `taxon` string column was passing the column-alias gate before
 *  this and getting flagged compatible (e.g. stacked_taxonomy_demo). */
const KIND_REQUIRES_DC_TYPE: Partial<Record<AdvancedVizKind, string>> = {
  phylogenetic: 'phylogeny',
};

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
  const hasSample = hasNamedDtype(ROLE_ALIASES.sample_id ?? [], STRING_LIKE);
  if (!hasSample) return null;
  const hasDim1 = hasNamedDtype(ROLE_ALIASES.dim_1 ?? [], NUMERIC_FLOAT);
  const hasDim2 = hasNamedDtype(ROLE_ALIASES.dim_2 ?? [], NUMERIC_FLOAT);
  if (hasDim1 && hasDim2) return 'precomputed';
  const numericCount = Object.values(schema).filter((d) =>
    NUMERIC_ANY.includes(d),
  ).length;
  return numericCount >= EMBEDDING_LIVE_MIN_NUMERIC ? 'live' : null;
}

/** Compatibility check: can the DC's schema satisfy a kind's required roles?
 *  Returns `null` when satisfied, otherwise a short reason for the tooltip.
 *
 *  Two-tier match: a role is satisfied iff the schema has at least one
 *  column with (a) an accepted dtype AND (b) a name in the role's alias list.
 *  Dtype-only was too permissive — any DC with one string + one float passed
 *  ten kinds — so unbound-but-numeric volcano data still showed Embedding,
 *  Manhattan, etc. as available.
 *
 *  Falls back to dtype-only when a role has no alias entry (so we don't
 *  accidentally hide everything when ROLE_ALIASES is incomplete). */
function unmetReason(
  kind: AdvancedVizKind,
  schema: Record<string, string> | null,
  dcConfigType: string | null,
): string | null {
  if (!schema) return null; // no schema yet → don't grey-out (avoid flashes)

  // Hard DC-type requirement (phylogenetic needs a phylogeny-type DC, not
  // any Table with a `taxon` column).
  const requiredDcType = KIND_REQUIRES_DC_TYPE[kind];
  if (requiredDcType && dcConfigType !== requiredDcType) {
    return `Needs a ${requiredDcType}-type data collection`;
  }

  // Embedding has two valid modes — precomputed (dim_1/dim_2 columns) or
  // live-compute (wide sample×feature matrix, Celery runs the reduction).
  // Either is sufficient; reject only if neither holds.
  if (kind === 'embedding') {
    return detectEmbeddingMode(schema)
      ? null
      : 'Needs: sample_id + either precomputed dim_1/dim_2 columns OR ≥10 numeric feature columns (for live PCA/UMAP/t-SNE/PCoA)';
  }

  const required = REQUIRED_ROLES[kind];
  const lowerSchema = Object.entries(schema).map(([name, dtype]) => ({
    name: name.toLowerCase(),
    dtype,
  }));
  const missing: string[] = [];
  for (const [role, accepted] of Object.entries(required)) {
    const aliases = ROLE_ALIASES[role];
    const hasDtype = lowerSchema.some(({ dtype }) => accepted.includes(dtype));
    const hasNameMatch = aliases
      ? lowerSchema.some(
          ({ name, dtype }) =>
            accepted.includes(dtype) && aliases.includes(name),
        )
      : hasDtype;
    if (!hasNameMatch) {
      missing.push(
        aliases
          ? `${role} (column named e.g. ${aliases.slice(0, 3).join('/')})`
          : `${role} (${accepted.join('/')})`,
      );
    }
  }
  const checkMinDtypeCount = (
    min: number | undefined,
    accepted: string[],
    label: string,
  ): void => {
    if (min == null) return;
    const count = lowerSchema.filter(({ dtype }) => accepted.includes(dtype)).length;
    if (count < min) missing.push(`≥${min} ${label}`);
  };
  checkMinDtypeCount(
    MIN_FLOAT_COLS[kind],
    NUMERIC_FLOAT,
    'float columns (continuous matrix for clustering)',
  );
  checkMinDtypeCount(
    MIN_INT_COLS[kind],
    NUMERIC_INT,
    'integer columns (binary 0/1 set indicators)',
  );
  if (missing.length === 0) return null;
  return `Needs: ${missing.join(', ')}`;
}

const AdvancedVizBuilder: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const wfId = useBuilderStore((s) => s.wfId);
  const dcConfigType = useBuilderStore((s) => s.dcConfigType);
  const config = useBuilderStore((s) => s.config) as {
    viz_kind?: AdvancedVizKind;
    column_mapping?: Record<string, string | string[]>;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const setPreviewReady = useBuilderStore((s) => s.setPreviewReady);

  const [kinds, setKinds] = useState<AdvancedVizKindDescriptor[] | null>(null);
  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [kindsError, setKindsError] = useState<string | null>(null);

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

  // Auto-suggest mappings on kind change. For embedding live-compute mode,
  // sample_id is the only required column binding; compute_method is a scalar
  // config field that defaults to "pca".
  useEffect(() => {
    if (!selectedKind || !schema) return;
    if (Object.keys(columnMapping).length > 0) return;

    const suggest: Record<string, string> = {};
    const lower = Object.keys(schema).reduce<Record<string, string>>((acc, c) => {
      acc[c.toLowerCase()] = c;
      return acc;
    }, {});
    const liveEmbeddingSuggest =
      selectedKind === 'embedding' && embeddingMode === 'live';
    const rolesToSuggest = liveEmbeddingSuggest
      ? { sample_id: REQUIRED_ROLES.embedding.sample_id }
      : REQUIRED_ROLES[selectedKind];
    for (const role of Object.keys(rolesToSuggest)) {
      const aliases = ROLE_ALIASES[role] || [role];
      for (const alias of aliases) {
        if (lower[alias]) {
          suggest[role] = lower[alias];
          break;
        }
      }
    }
    if (liveEmbeddingSuggest) {
      // Default the compute method to PCA; user can change in the dropdown.
      (suggest as Record<string, string>).compute_method = 'pca';
    }
    if (Object.keys(suggest).length > 0) {
      patchConfig({ column_mapping: { ...columnMapping, ...suggest } });
    }
  }, [selectedKind, schema, columnMapping, patchConfig, embeddingMode]);

  const setKind = (kind: AdvancedVizKind | null) => {
    patchConfig({ viz_kind: kind || undefined, column_mapping: {} });
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

  const validation = useMemo(() => {
    if (!selectedKind || !schema) return { errors: [], ok: false };
    const errors: string[] = [];
    const required = liveEmbedding
      ? { sample_id: REQUIRED_ROLES.embedding.sample_id }
      : REQUIRED_ROLES[selectedKind];
    for (const [role, accepted] of Object.entries(required)) {
      const val = columnMapping[role];
      if (!val) {
        errors.push(`Required role "${role}" is not bound`);
        continue;
      }
      const cols = Array.isArray(val) ? val : [val];
      for (const col of cols) {
        const dtype = schema[col];
        if (!dtype) {
          errors.push(`Column "${col}" (role "${role}") is not in the DC`);
        } else if (!accepted.includes(dtype)) {
          errors.push(
            `Column "${col}" (role "${role}") has dtype ${dtype}; expected one of ${accepted.join(', ')}`,
          );
        }
      }
    }
    // Sunburst: rank_cols must have at least 2 columns.
    if (selectedKind === 'sunburst') {
      const ranks = columnMapping.ranks;
      if (!Array.isArray(ranks) || ranks.length < 2) {
        errors.push('Sunburst needs at least 2 rank columns');
      }
    }
    const optional = OPTIONAL_ROLES[selectedKind];
    for (const [role, accepted] of Object.entries(optional)) {
      const val = columnMapping[role];
      if (!val) continue;
      const cols = Array.isArray(val) ? val : [val];
      for (const col of cols) {
        const dtype = schema[col];
        if (!dtype) {
          errors.push(`Optional column "${col}" (role "${role}") is not in the DC`);
        } else if (!accepted.includes(dtype)) {
          errors.push(
            `Optional column "${col}" (role "${role}") has dtype ${dtype}; expected one of ${accepted.join(', ')}`,
          );
        }
      }
    }
    if (liveEmbedding && !columnMapping.compute_method) {
      errors.push('Pick a compute method (PCA / UMAP / t-SNE / PCoA)');
    }
    return { errors, ok: errors.length === 0 };
  }, [selectedKind, schema, columnMapping, liveEmbedding]);

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

  const columnOptions = (accepted: string[]): { value: string; label: string }[] => {
    if (!schema) return [];
    return Object.entries(schema)
      .filter(([, dtype]) => accepted.includes(dtype))
      .map(([name, dtype]) => ({ value: name, label: `${name} : ${dtype}` }));
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

  // Split into kinds the bound DC can satisfy vs. the rest. When no schema
  // is loaded yet (no DC picked), treat everything as available so the user
  // sees the full picker.
  const { availableKinds, unavailableKinds } = useMemo(() => {
    if (!schema) return { availableKinds: matchedKinds, unavailableKinds: [] };
    const ok: typeof matchedKinds = [];
    const blocked: typeof matchedKinds = [];
    for (const k of matchedKinds) {
      (unmetReason(k.viz_kind, schema, dcConfigType) ? blocked : ok).push(k);
    }
    return { availableKinds: ok, unavailableKinds: blocked };
  }, [matchedKinds, schema, dcConfigType]);

  /** Render a titled grid of kind tiles. `dim=true` is used for the
   *  unavailable accordion (greyed-out + tooltip with unmet reason). */
  const renderKindSection = (
    title: string | null,
    items: AdvancedVizKindDescriptor[],
    dim: boolean,
    subtitle?: string,
  ): React.ReactNode => {
    if (items.length === 0) return null;
    return (
      <Stack gap={6}>
        {title ? (
          <Group gap="xs" align="baseline">
            <Text fw={600} size="sm">{title}</Text>
            {subtitle ? (
              <Text size="xs" c="dimmed">{subtitle}</Text>
            ) : null}
          </Group>
        ) : null}
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }} spacing="sm">
          {items.map((k) => {
            const isSelected = selectedKind === k.viz_kind;
            const reason = dim ? unmetReason(k.viz_kind, schema, dcConfigType) : null;
            const disabled = !!reason;
            const tile = (
              <Paper
                withBorder
                p="sm"
                radius="md"
                onClick={() => {
                  if (disabled) return;
                  setKind(k.viz_kind);
                }}
                style={{
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: dim ? 0.5 : 1,
                  borderColor: isSelected ? 'var(--mantine-color-pink-6)' : undefined,
                  background: isSelected ? 'var(--mantine-color-pink-0)' : undefined,
                  transition: 'transform 120ms ease, box-shadow 120ms ease',
                  transform: isSelected ? 'translateY(-1px)' : undefined,
                }}
              >
                <Stack gap={6}>
                  <Group gap={6} wrap="nowrap">
                    <Icon icon={k.icon} width={18} height={18} />
                    <Text fw={600} size="sm" lineClamp={1}>{k.label}</Text>
                  </Group>
                  <Text size="xs" c="dimmed" lineClamp={3}>{k.description}</Text>
                  {isSelected ? <Badge size="xs" color="pink">selected</Badge> : null}
                </Stack>
              </Paper>
            );
            return (
              <div key={k.viz_kind}>
                {disabled && reason ? (
                  <Tooltip label={reason} multiline w={260} withinPortal>
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
        Pick a viz kind, then bind each required role to a column from the chosen
        data collection. The picker shows kinds compatible with this DC; expand
        "other kinds" below to see ones that need a different schema.
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

      {/* Single "Visualisations" section — kinds previously split into
          "Statistical tools" (manhattan / ancombc / da_barplot / enrichment)
          are now folded in. The backend `category: "tool"` field is kept on
          the metadata payload for future per-family grouping but no longer
          drives picker layout. */}
      {renderKindSection('Visualisations', availableKinds, false)}

      {unavailableKinds.length > 0 ? (
        <Accordion variant="contained" defaultValue={null}>
          <Accordion.Item value="unavailable">
            <Accordion.Control>
              <Text size="sm" c="dimmed">
                {unavailableKinds.length} other kinds need different data — show them anyway
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              {renderKindSection(null, unavailableKinds, true)}
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      ) : null}

      {selectedKind ? (
        <Paper withBorder p="md" radius="md">
          <Stack gap="xs">
            <Text fw={600}>Column bindings</Text>
            <Paper withBorder p="xs" radius="sm">
              <Stack gap={4}>
                <Text size="xs" fw={500}>Example input columns</Text>
                <Text size="xs" c="dimmed">
                  Your data collection needs at least these columns (any accepted dtype works).
                </Text>
                <Table withTableBorder withColumnBorders striped fz="xs">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Role</Table.Th>
                      <Table.Th>Accepted dtypes</Table.Th>
                      <Table.Th>Required?</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {Object.entries(REQUIRED_ROLES[selectedKind])
                      .filter(
                        ([role]) =>
                          !liveEmbedding || (role !== 'dim_1' && role !== 'dim_2'),
                      )
                      .map(([role, accepted]) => (
                      <Table.Tr key={`req-${role}`}>
                        <Table.Td>{role}</Table.Td>
                        <Table.Td>{accepted.join(' / ')}</Table.Td>
                        <Table.Td>required</Table.Td>
                      </Table.Tr>
                    ))}
                    {liveEmbedding ? (
                      <Table.Tr key="req-compute_method">
                        <Table.Td>compute_method</Table.Td>
                        <Table.Td>pca / umap / tsne / pcoa</Table.Td>
                        <Table.Td>required</Table.Td>
                      </Table.Tr>
                    ) : null}
                    {Object.entries(OPTIONAL_ROLES[selectedKind]).map(([role, accepted]) => (
                      <Table.Tr key={`opt-${role}`}>
                        <Table.Td>{role}</Table.Td>
                        <Table.Td>{accepted.join(' / ')}</Table.Td>
                        <Table.Td>optional</Table.Td>
                      </Table.Tr>
                    ))}
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
                    label="ranks (required, hierarchy root→leaf)"
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
                {Object.entries(REQUIRED_ROLES[selectedKind])
                  .filter(
                    // Skip dim_1/dim_2 when running embedding live — the
                    // Celery task derives them.
                    ([role]) =>
                      !liveEmbedding || (role !== 'dim_1' && role !== 'dim_2'),
                  )
                  .map(([role, accepted]) => (
                  <Select
                    key={role}
                    label={`${role} (required, ${accepted.join('/')})`}
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
                {Object.entries(OPTIONAL_ROLES[selectedKind]).map(([role, accepted]) => (
                  <Select
                    key={role}
                    label={`${role} (optional, ${accepted.join('/')})`}
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
        />
      ) : null}
    </Stack>
  );
};

export default AdvancedVizBuilder;

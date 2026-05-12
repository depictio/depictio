/**
 * Builder for the advanced_viz component family.
 *
 * Two-step inside the per-type panel:
 *   1) Pick viz_kind (volcano / embedding / manhattan / stacked_taxonomy)
 *   2) Bind each required role to a column from the chosen DC, with
 *      editor-time validation against the DC's polars schema.
 *
 * Validation is enforced via depictio/models/components/advanced_viz/
 * schemas.py (server side) and mirrored here with a lightweight client-side
 * check so Save is only enabled once required roles are mapped to existing
 * columns of an acceptable dtype.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Group,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';

import {
  AdvancedVizKind,
  AdvancedVizKindDescriptor,
  fetchAdvancedVizKinds,
  fetchPolarsSchema,
} from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';

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
};

const OPTIONAL_ROLES: Record<AdvancedVizKind, Record<string, string[]>> = {
  volcano: {
    label: STRING_LIKE,
    category: STRING_LIKE,
  },
  embedding: {
    dim_3: NUMERIC_FLOAT,
    cluster: STRING_LIKE,
    color: [...NUMERIC_ANY, ...STRING_LIKE],
  },
  manhattan: {
    feature: STRING_LIKE,
    effect: NUMERIC_FLOAT,
  },
  stacked_taxonomy: {},
};

const KIND_PRETTY: Record<AdvancedVizKind, string> = {
  volcano: 'Volcano',
  embedding: 'Embedding',
  manhattan: 'Manhattan / GWAS',
  stacked_taxonomy: 'Stacked taxonomy',
};

const AdvancedVizBuilder: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    viz_kind?: AdvancedVizKind;
    column_mapping?: Record<string, string>;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [kinds, setKinds] = useState<AdvancedVizKindDescriptor[] | null>(null);
  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [kindsError, setKindsError] = useState<string | null>(null);

  // Load kinds metadata once.
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

  // Load DC polars schema whenever the bound DC changes.
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
  const columnMapping = useMemo(() => config.column_mapping || {}, [config.column_mapping]);

  // Edit-mode unpack: when a saved component is loaded into the builder, the
  // store's `config` slot contains the persisted stored_metadata. The
  // per-kind binding sits under `config.config.<role>_col`. Translate it
  // back into the role→column map this builder UI consumes.
  useEffect(() => {
    if (Object.keys(columnMapping).length > 0) return;
    const persistedConfig = (config as unknown as { config?: Record<string, unknown> })
      .config;
    if (!persistedConfig || typeof persistedConfig !== 'object') return;
    const recovered: Record<string, string> = {};
    for (const [k, v] of Object.entries(persistedConfig)) {
      if (k.endsWith('_col') && typeof v === 'string') {
        recovered[k.slice(0, -'_col'.length)] = v;
      }
    }
    if (Object.keys(recovered).length > 0) {
      patchConfig({ column_mapping: recovered });
    }
  }, [config, columnMapping, patchConfig]);

  // Auto-suggest mappings on kind change.
  useEffect(() => {
    if (!selectedKind || !schema) return;
    const current = columnMapping;
    if (Object.keys(current).length > 0) return; // user already started binding

    const suggest: Record<string, string> = {};
    const lower = Object.keys(schema).reduce<Record<string, string>>((acc, c) => {
      acc[c.toLowerCase()] = c;
      return acc;
    }, {});
    const roles = REQUIRED_ROLES[selectedKind];
    for (const role of Object.keys(roles)) {
      const lowerRole = role.toLowerCase();
      // exact match first, then a known alias.
      const aliases: string[] = (
        {
          feature_id: ['feature_id', 'gene', 'id', 'feature', 'taxon'],
          effect_size: ['effect_size', 'lfc', 'log2foldchange', 'effect'],
          significance: ['significance', 'padj', 'q_val', 'qvalue', 'pvalue', 'p_val'],
          sample_id: ['sample_id', 'sample', 'sampleid', 'sample_name'],
          dim_1: ['dim_1', 'pc1', 'umap1', 'tsne1'],
          dim_2: ['dim_2', 'pc2', 'umap2', 'tsne2'],
          chr: ['chr', 'chrom', 'chromosome'],
          pos: ['pos', 'position', 'start'],
          score: ['score', 'pvalue', 'p_val', 'qvalue', 'q_val', 'neg_log10_qval'],
          taxon: ['taxon', 'taxonomy', 'name'],
          rank: ['rank', 'level'],
          abundance: ['abundance', 'rel_abundance', 'count', 'value'],
        } as Record<string, string[]>
      )[role] || [role];
      for (const alias of aliases) {
        if (lower[alias]) {
          suggest[role] = lower[alias];
          break;
        }
      }
    }
    if (Object.keys(suggest).length > 0) {
      patchConfig({ column_mapping: { ...current, ...suggest } });
    }
  }, [selectedKind, schema, columnMapping, patchConfig]);

  const setKind = (kind: AdvancedVizKind | null) => {
    patchConfig({ viz_kind: kind || undefined, column_mapping: {} });
  };

  const setRole = (role: string, col: string | null) => {
    const next = { ...columnMapping };
    if (col) next[role] = col;
    else delete next[role];
    patchConfig({ column_mapping: next });
  };

  const validation = useMemo(() => {
    if (!selectedKind || !schema) return { errors: [], ok: false };
    const errors: string[] = [];
    const required = REQUIRED_ROLES[selectedKind];
    for (const [role, accepted] of Object.entries(required)) {
      const col = columnMapping[role];
      if (!col) {
        errors.push(`Required role "${role}" is not bound`);
        continue;
      }
      const dtype = schema[col];
      if (!dtype) {
        errors.push(`Column "${col}" (role "${role}") is not in the DC`);
        continue;
      }
      if (!accepted.includes(dtype)) {
        errors.push(
          `Column "${col}" (role "${role}") has dtype ${dtype}; expected one of ${accepted.join(', ')}`,
        );
      }
    }
    const optional = OPTIONAL_ROLES[selectedKind];
    for (const [role, accepted] of Object.entries(optional)) {
      const col = columnMapping[role];
      if (!col) continue;
      const dtype = schema[col];
      if (!dtype) {
        errors.push(`Optional column "${col}" (role "${role}") is not in the DC`);
        continue;
      }
      if (!accepted.includes(dtype)) {
        errors.push(
          `Optional column "${col}" (role "${role}") has dtype ${dtype}; expected one of ${accepted.join(', ')}`,
        );
      }
    }
    return { errors, ok: errors.length === 0 };
  }, [selectedKind, schema, columnMapping]);

  // Expose validation result to the parent stepper via the builder store so the
  // Save button can read it. We piggy-back on the existing saveError slot:
  // empty string = valid, otherwise a human-readable joined message.
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

  return (
    <Stack gap="md">
      <Title order={4}>Advanced visualisation</Title>
      <Text size="sm" c="dimmed">
        Pick a viz kind, then bind each required role to a column from the chosen
        data collection. Bindings are validated against the DC's polars schema.
      </Text>

      {kindsError ? (
        <Alert color="red" title="Failed to load viz kinds">
          {kindsError}
        </Alert>
      ) : null}

      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
        {(kinds || []).map((k) => {
          const isSelected = selectedKind === k.viz_kind;
          return (
            <Paper
              key={k.viz_kind}
              withBorder
              p="sm"
              radius="md"
              onClick={() => setKind(k.viz_kind)}
              style={{
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--mantine-color-pink-6)' : undefined,
                background: isSelected ? 'var(--mantine-color-pink-0)' : undefined,
              }}
            >
              <Stack gap={4}>
                <Group gap="xs" justify="space-between">
                  <Text fw={600}>{KIND_PRETTY[k.viz_kind]}</Text>
                  {isSelected ? <Badge size="sm" color="pink">selected</Badge> : null}
                </Group>
                <Text size="xs" c="dimmed">{k.description}</Text>
              </Stack>
            </Paper>
          );
        })}
      </SimpleGrid>

      {selectedKind ? (
        <Paper withBorder p="md" radius="md">
          <Stack gap="xs">
            <Text fw={600}>Column bindings</Text>
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
                {Object.entries(REQUIRED_ROLES[selectedKind]).map(([role, accepted]) => (
                  <Select
                    key={role}
                    label={`${role} (required, ${accepted.join('/')})`}
                    placeholder="Pick a column"
                    value={columnMapping[role] || null}
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
                    value={columnMapping[role] || null}
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
                ) : (
                  <Alert color="teal" variant="light">
                    <Text size="xs">Bindings look good — ready to save.</Text>
                  </Alert>
                )}
              </>
            )}
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
};

export default AdvancedVizBuilder;

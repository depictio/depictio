import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  createProjectLink,
  fetchMultiQCSampleMappings,
  fetchSpecs,
  updateProjectLink,
} from 'depictio-react-core';
import type {
  CreateLinkInput,
  DCLink,
  DCLinkConfig,
  LinkResolverName,
  LinkTargetType,
  ResolverInfo,
  UpdateLinkInput,
} from 'depictio-react-core';

interface DataCollectionOption {
  id: string;
  tag: string;
  /** DC type from `config.type` — used to infer `target_type` for the link. */
  type: string;
}

interface LinkEditModalProps {
  opened: boolean;
  projectId: string;
  /** When set, modal is in edit mode. When null, it's create mode. */
  link: DCLink | null;
  /** All DCs in the project — populates the source/target dropdowns. */
  dataCollections: DataCollectionOption[];
  /** Resolver catalog from `listLinkResolvers`. Falls back to a static list
   *  if the backend's resolvers endpoint isn't reachable. */
  resolvers: ResolverInfo[];
  onClose: () => void;
  /** Fired after a successful save so the parent can refresh its link list. */
  onSaved: (link: DCLink) => void;
}

const RESOLVER_FALLBACK: ResolverInfo[] = [
  { name: 'direct', label: 'Direct', description: 'Pass source value through unchanged.' },
  {
    name: 'sample_mapping',
    label: 'Sample mapping',
    description: 'Expand a canonical sample ID to all of its MultiQC variants.',
  },
  {
    name: 'pattern',
    label: 'Pattern',
    description: 'Substitute the source value into a template like {sample}.bam.',
  },
  {
    name: 'regex',
    label: 'Regex',
    description: 'Match target rows whose target_field matches a regex.',
  },
  {
    name: 'wildcard',
    label: 'Wildcard',
    description: 'Glob-style * / ? match against the target_field.',
  },
];

const inferTargetType = (dc: DataCollectionOption | undefined): LinkTargetType => {
  if (!dc) return 'table';
  if (dc.type === 'multiqc') return 'multiqc';
  if (dc.type === 'image') return 'image';
  return 'table';
};

const LinkEditModal: React.FC<LinkEditModalProps> = ({
  opened,
  projectId,
  link,
  dataCollections,
  resolvers,
  onClose,
  onSaved,
}) => {
  const editing = !!link;
  const resolverList = resolvers.length ? resolvers : RESOLVER_FALLBACK;

  const [sourceDcId, setSourceDcId] = useState('');
  const [sourceColumn, setSourceColumn] = useState('');
  const [targetDcId, setTargetDcId] = useState('');
  const [resolver, setResolver] = useState<LinkResolverName>('direct');
  const [targetField, setTargetField] = useState('');
  const [pattern, setPattern] = useState('');
  const [mappingsJson, setMappingsJson] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(true);
  const [description, setDescription] = useState('');
  const [enabled, setEnabled] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoMappings, setAutoMappings] = useState<Record<string, string[]> | null>(null);
  const [autoMappingsLoading, setAutoMappingsLoading] = useState(false);

  // Reset fields whenever the modal opens or the editing target changes.
  useEffect(() => {
    if (!opened) return;
    setError(null);
    setSubmitting(false);
    setAutoMappings(null);
    if (link) {
      setSourceDcId(link.source_dc_id);
      setSourceColumn(link.source_column);
      setTargetDcId(link.target_dc_id);
      setResolver(link.link_config?.resolver || 'direct');
      setTargetField(link.link_config?.target_field || '');
      setPattern(link.link_config?.pattern || '');
      setMappingsJson(
        link.link_config?.mappings
          ? JSON.stringify(link.link_config.mappings, null, 2)
          : '',
      );
      setCaseSensitive(link.link_config?.case_sensitive ?? true);
      setDescription(link.description || '');
      setEnabled(link.enabled);
    } else {
      setSourceDcId('');
      setSourceColumn('');
      setTargetDcId('');
      setResolver('direct');
      setTargetField('');
      setPattern('');
      setMappingsJson('');
      setCaseSensitive(true);
      setDescription('');
      setEnabled(true);
    }
  }, [opened, link]);

  const targetDc = useMemo(
    () => dataCollections.find((d) => d.id === targetDcId),
    [dataCollections, targetDcId],
  );
  const targetType = inferTargetType(targetDc);

  // Mantine Select crashes on options with falsy `value`, so filter ids
  // defensively at every site.
  const toDcOption = (d: DataCollectionOption) => ({
    value: d.id,
    label: `${d.tag}${d.type ? ` · ${d.type}` : ''}`,
  });

  // Source MUST be a table DC — only tables expose tabular columns that can
  // be filtered. MultiQC / image / etc. as the source side has no clean
  // "column to filter on" semantic.
  const sourceDcOptions = useMemo(
    () => dataCollections.filter((d) => d.id && d.type === 'table').map(toDcOption),
    [dataCollections],
  );

  // Target DCs: any DC type, but exclude whichever DC the user picked as
  // source so they can't link a DC to itself.
  const targetDcOptions = useMemo(
    () => dataCollections.filter((d) => d.id && d.id !== sourceDcId).map(toDcOption),
    [dataCollections, sourceDcId],
  );

  // Source column dropdown: load the source DC's column specs and surface
  // them as options. Free-text was error-prone — users would mistype the
  // column name and the link would silently match nothing at runtime.
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [sourceColumnsLoading, setSourceColumnsLoading] = useState(false);
  useEffect(() => {
    if (!sourceDcId) {
      setSourceColumns([]);
      return;
    }
    let cancelled = false;
    setSourceColumnsLoading(true);
    fetchSpecs(sourceDcId)
      .then((specs) => {
        if (cancelled) return;
        // /deltatables/specs/{dcId} returns either an array of
        // {name, type, specs} entries or a dict keyed by column name.
        let cols: string[] = [];
        if (Array.isArray(specs)) {
          cols = (specs as Array<{ name?: string }>)
            .map((s) => s?.name || '')
            .filter(Boolean);
        } else if (specs && typeof specs === 'object') {
          cols = Object.keys(specs);
        }
        setSourceColumns(cols);
      })
      .catch(() => {
        if (!cancelled) setSourceColumns([]);
      })
      .finally(() => {
        if (!cancelled) setSourceColumnsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceDcId]);

  const sourceColumnOptions = useMemo(
    () => sourceColumns.map((c) => ({ value: c, label: c })),
    [sourceColumns],
  );

  // Auto-pick a sensible resolver only when the target *type* transitions.
  // If we keyed this on `targetDcId` too, switching between two MultiQC DCs
  // would clobber whatever resolver the user picked manually — same DC type,
  // different DC, no reason to overwrite. Skip in edit mode so saved links
  // retain their stored resolver until the user explicitly changes it.
  useEffect(() => {
    if (editing) return;
    if (!targetDcId) return;
    const auto: LinkResolverName =
      targetType === 'multiqc' ? 'sample_mapping' : 'direct';
    setResolver(auto);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType]);

  // Auto-load aggregated sample mappings for sample_mapping + multiqc.
  useEffect(() => {
    if (!opened) return;
    if (resolver !== 'sample_mapping' || targetType !== 'multiqc' || !targetDcId) {
      setAutoMappings(null);
      return;
    }
    setAutoMappingsLoading(true);
    fetchMultiQCSampleMappings(projectId, targetDcId)
      .then((m) => setAutoMappings(m))
      .catch(() => setAutoMappings(null))
      .finally(() => setAutoMappingsLoading(false));
  }, [opened, projectId, resolver, targetType, targetDcId]);

  const buildLinkConfig = (): DCLinkConfig | null => {
    if (resolver === 'direct') {
      return { resolver, target_field: targetField || undefined };
    }
    if (resolver === 'pattern') {
      if (!pattern.trim()) {
        setError('Pattern is required for the pattern resolver.');
        return null;
      }
      return {
        resolver,
        pattern: pattern.trim(),
        target_field: targetField || undefined,
      };
    }
    if (resolver === 'regex' || resolver === 'wildcard') {
      if (!targetField.trim()) {
        setError(`${resolver} resolver needs a target_field.`);
        return null;
      }
      return {
        resolver,
        target_field: targetField.trim(),
        case_sensitive: caseSensitive,
      };
    }
    if (resolver === 'sample_mapping') {
      // Prefer the auto-loaded MultiQC mappings; otherwise parse JSON textarea.
      let mappings: Record<string, string[]> | undefined;
      if (autoMappings) {
        mappings = autoMappings;
      } else if (mappingsJson.trim()) {
        try {
          mappings = JSON.parse(mappingsJson);
        } catch (err) {
          setError(`Invalid mappings JSON: ${(err as Error).message}`);
          return null;
        }
      }
      return {
        resolver,
        mappings,
        target_field: targetField || undefined,
      };
    }
    return { resolver };
  };

  const validate = (): boolean => {
    if (!sourceDcId || !targetDcId) {
      setError('Source and target data collections are required.');
      return false;
    }
    if (sourceDcId === targetDcId) {
      setError('Source and target must be different data collections.');
      return false;
    }
    if (!sourceColumn.trim()) {
      setError('Source column is required.');
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    setError(null);
    if (!validate()) return;
    const link_config = buildLinkConfig();
    if (!link_config) return;

    const payload: CreateLinkInput = {
      source_dc_id: sourceDcId,
      source_column: sourceColumn.trim(),
      target_dc_id: targetDcId,
      target_type: targetType,
      link_config,
      description: description.trim() || undefined,
      enabled,
    };

    setSubmitting(true);
    try {
      const saved = editing
        ? await updateProjectLink(projectId, link!.id, payload as UpdateLinkInput)
        : await createProjectLink(projectId, payload);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError((err as Error).message || 'Failed to save link.');
    } finally {
      setSubmitting(false);
    }
  };

  const resolverOptions = resolverList
    .filter((r) => r && r.name)
    .map((r) => ({ value: r.name, label: r.label || r.name }));
  const resolverInfo = resolverList.find((r) => r.name === resolver);

  return (
    <Modal
      opened={opened}
      onClose={submitting ? () => {} : onClose}
      title={editing ? 'Edit cross-DC link' : 'Create cross-DC link'}
      size="lg"
      closeOnClickOutside={!submitting}
      closeOnEscape={!submitting}
    >
      <Stack gap="md">
        {error && (
          <Alert color="red" icon={<Icon icon="mdi:alert-circle" width={18} />}>
            {error}
          </Alert>
        )}

        <Group grow align="flex-start">
          <Select
            label="Source data collection"
            placeholder="Pick a table DC"
            data={sourceDcOptions}
            value={sourceDcId}
            onChange={(v) => {
              const next = v || '';
              setSourceDcId(next);
              // Drop the source column when the source DC changes so we
              // don't carry over a column name that doesn't exist on the
              // new source. Also clear the target if it just became the
              // same DC (Mantine Select can race state momentarily).
              setSourceColumn('');
              if (next && next === targetDcId) setTargetDcId('');
            }}
            searchable
            required
            description="Only table DCs can act as a filter source."
            nothingFoundMessage="No table data collections in this project."
          />
          <Select
            label="Source column"
            placeholder={
              !sourceDcId
                ? 'Pick a source DC first'
                : sourceColumnsLoading
                  ? 'Loading columns…'
                  : 'Pick a column'
            }
            data={sourceColumnOptions}
            value={sourceColumn || null}
            onChange={(v) => setSourceColumn(v || '')}
            disabled={!sourceDcId || sourceColumnsLoading}
            searchable
            required
            nothingFoundMessage="No columns available."
          />
        </Group>

        <Select
          label="Target data collection"
          placeholder={!sourceDcId ? 'Pick a source DC first' : 'Select a DC'}
          data={targetDcOptions}
          value={targetDcId}
          onChange={(v) => setTargetDcId(v || '')}
          disabled={!sourceDcId}
          searchable
          required
          description={`Detected target type: ${targetType}`}
        />

        <Select
          label="Resolver"
          data={resolverOptions}
          value={resolver}
          onChange={(v) => setResolver((v as LinkResolverName) || 'direct')}
          allowDeselect={false}
          description={resolverInfo?.description}
        />

        {/* Per-resolver config */}
        {resolver === 'direct' && (
          <TextInput
            label="Target field (optional)"
            placeholder="Leave blank to match against the joined-on column"
            value={targetField}
            onChange={(e) => setTargetField(e.currentTarget.value)}
          />
        )}
        {resolver === 'pattern' && (
          <Stack gap="xs">
            <TextInput
              label="Pattern"
              placeholder="{sample}.bam"
              value={pattern}
              onChange={(e) => setPattern(e.currentTarget.value)}
              required
              description="Use {sample} as the placeholder for the source value."
            />
            <TextInput
              label="Target field"
              value={targetField}
              onChange={(e) => setTargetField(e.currentTarget.value)}
            />
          </Stack>
        )}
        {(resolver === 'regex' || resolver === 'wildcard') && (
          <Stack gap="xs">
            <TextInput
              label="Target field"
              value={targetField}
              onChange={(e) => setTargetField(e.currentTarget.value)}
              required
            />
            <Switch
              label="Case sensitive"
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.currentTarget.checked)}
            />
          </Stack>
        )}
        {resolver === 'sample_mapping' && (
          <SampleMappingEditor
            targetType={targetType}
            autoMappings={autoMappings}
            autoMappingsLoading={autoMappingsLoading}
            mappingsJson={mappingsJson}
            onMappingsJsonChange={setMappingsJson}
            targetField={targetField}
            onTargetFieldChange={setTargetField}
          />
        )}

        <Textarea
          label="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={4}
        />

        <Switch
          label="Enabled"
          checked={enabled}
          onChange={(e) => setEnabled(e.currentTarget.checked)}
        />

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} loading={submitting}>
            {editing ? 'Save changes' : 'Create link'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

interface SampleMappingEditorProps {
  targetType: LinkTargetType;
  autoMappings: Record<string, string[]> | null;
  autoMappingsLoading: boolean;
  mappingsJson: string;
  onMappingsJsonChange: (v: string) => void;
  targetField: string;
  onTargetFieldChange: (v: string) => void;
}

const SampleMappingEditor: React.FC<SampleMappingEditorProps> = ({
  targetType,
  autoMappings,
  autoMappingsLoading,
  mappingsJson,
  onMappingsJsonChange,
  targetField,
  onTargetFieldChange,
}) => {
  if (targetType === 'multiqc') {
    return (
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          Sample mappings (auto-loaded from the MultiQC reports)
        </Text>
        <Box
          style={{
            border: '1px solid var(--mantine-color-default-border)',
            borderRadius: 6,
            padding: 8,
            background: 'var(--mantine-color-default-hover)',
          }}
        >
          {autoMappingsLoading && <Text size="sm">Loading mappings…</Text>}
          {!autoMappingsLoading && autoMappings && Object.keys(autoMappings).length > 0 && (
            <ScrollArea h={180}>
              <Table verticalSpacing="xs" fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Canonical</Table.Th>
                    <Table.Th>Variants</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {Object.entries(autoMappings).map(([canonical, variants]) => (
                    <Table.Tr key={canonical}>
                      <Table.Td>
                        <Code>{canonical}</Code>
                      </Table.Td>
                      <Table.Td>
                        {variants.map((v) => (
                          <Code key={v} mr={4}>
                            {v}
                          </Code>
                        ))}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}
          {!autoMappingsLoading &&
            (!autoMappings || Object.keys(autoMappings).length === 0) && (
              <Text size="sm" c="dimmed">
                No mappings yet — the target MultiQC DC has no reports, or
                sample-mapping aggregation hasn't run.
              </Text>
            )}
        </Box>
        <Text size="xs" c="dimmed">
          Mappings are read-only in v1. The link will use whatever the server
          returns at resolution time.
        </Text>
      </Stack>
    );
  }
  return (
    <Stack gap="xs">
      <Textarea
        label="Mappings (JSON)"
        placeholder='{"HG001": ["HG001_R1", "HG001_R2"]}'
        value={mappingsJson}
        onChange={(e) => onMappingsJsonChange(e.currentTarget.value)}
        autosize
        minRows={3}
        maxRows={10}
      />
      <TextInput
        label="Target field (optional)"
        value={targetField}
        onChange={(e) => onTargetFieldChange(e.currentTarget.value)}
      />
    </Stack>
  );
};

export default LinkEditModal;

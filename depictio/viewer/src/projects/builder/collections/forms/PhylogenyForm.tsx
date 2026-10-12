/**
 * Phylogeny properties: the tree format, ladderizing, and the table
 * collection of this project that holds per-taxon metadata.
 */
import React from 'react';
import { Group, SegmentedControl, Select, Stack, Switch, Text, TextInput } from '@mantine/core';

import type { BuilderPhylogenyProps } from 'depictio-react-core';

export const PhylogenyForm: React.FC<{
  props: BuilderPhylogenyProps;
  onChange: (props: BuilderPhylogenyProps) => void;
  /** Tags of the project's table collections. */
  tables: string[];
}> = ({ props, onChange, tables }) => {
  const meta = props.metadata_dc_tag ?? null;
  const missing = Boolean(meta && !tables.includes(meta));
  return (
    <Stack gap="xs">
      <Group align="flex-end" justify="space-between">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Format
          </Text>
          <SegmentedControl
            size="xs"
            value={props.format}
            data={[
              { value: 'newick', label: 'Newick' },
              { value: 'nexus', label: 'Nexus' },
            ]}
            onChange={(v) => onChange({ ...props, format: v === 'nexus' ? 'nexus' : 'newick' })}
          />
        </Stack>
        <Switch
          label="Ladderize"
          checked={props.ladderize ?? true}
          onChange={(e) => onChange({ ...props, ladderize: e.currentTarget.checked })}
        />
      </Group>
      <Group grow align="flex-start">
        <Select
          label="Metadata table"
          description={
            tables.length ? 'A table collection with one row per taxon' : 'Add a table collection first'
          }
          placeholder="None"
          value={meta}
          data={missing && meta ? [meta, ...tables] : tables}
          clearable
          disabled={tables.length === 0 && !meta}
          onChange={(v) =>
            onChange({
              ...props,
              metadata_dc_tag: v,
              metadata_taxon_column: v ? props.metadata_taxon_column ?? null : null,
            })
          }
          error={missing ? 'Not a table collection of this project.' : undefined}
          data-testid="builder-props-phylogeny-metadata"
        />
        <TextInput
          label="Taxon column"
          description="The metadata column matching the tip labels"
          placeholder="taxon"
          disabled={!meta}
          value={props.metadata_taxon_column ?? ''}
          onChange={(e) => onChange({ ...props, metadata_taxon_column: e.currentTarget.value })}
        />
      </Group>
      <Select
        label="Tip labels"
        value={props.tip_label_strategy ?? 'taxon'}
        data={[
          { value: 'taxon', label: 'The whole label is the taxon' },
          { value: 'first_token', label: 'The first token of the label is the taxon' },
        ]}
        allowDeselect={false}
        onChange={(v) =>
          onChange({ ...props, tip_label_strategy: v === 'first_token' ? 'first_token' : 'taxon' })
        }
      />
    </Stack>
  );
};

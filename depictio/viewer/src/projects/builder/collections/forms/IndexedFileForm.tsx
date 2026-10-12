/**
 * Indexed file properties (the formats GenomeSpy reads lazily: VCF, BAM, bigWig,
 * bigBed, GFF3, FASTA, any tabix file): the format, the index next to each file,
 * how a sample is named, and the assembly.
 */
import React from 'react';
import { Group, NumberInput, Select, Stack, TextInput } from '@mantine/core';

import type { BuilderIndexedFileProps } from 'depictio-react-core';

// The server's IndexedFileFormat, in the same order.
const FORMATS = [
  { value: 'vcf', label: 'VCF (bgzipped)' },
  { value: 'bam', label: 'BAM' },
  { value: 'bigwig', label: 'bigWig' },
  { value: 'bigbed', label: 'bigBed' },
  { value: 'gff3', label: 'GFF3 (bgzipped)' },
  { value: 'fasta', label: 'FASTA' },
  { value: 'tabix', label: 'Other tabix file (BED, bedGraph...)' },
];

/** The index each format needs, as the server defaults it (none: self-indexed). */
const INDEX_HINT: Record<string, string> = {
  vcf: '.tbi',
  bam: '.bai',
  gff3: '.tbi',
  tabix: '.tbi',
  fasta: '.fai',
  bigwig: 'none (self-indexed)',
  bigbed: 'none (self-indexed)',
};

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

export const IndexedFileForm: React.FC<{
  props: BuilderIndexedFileProps;
  onChange: (props: BuilderIndexedFileProps) => void;
}> = ({ props, onChange }) => {
  const formats = FORMATS.some((f) => f.value === props.format)
    ? FORMATS
    : [{ value: props.format, label: props.format }, ...FORMATS];
  return (
    <Stack gap="xs">
      <Group grow align="flex-start">
        <Select
          label="Format"
          value={props.format}
          data={formats}
          allowDeselect={false}
          onChange={(v) => onChange({ ...props, format: v || 'vcf' })}
          data-testid="builder-props-indexed-format"
        />
        <TextInput
          label="Index suffix"
          description="Blank for the usual one"
          placeholder={INDEX_HINT[props.format] ?? 'none'}
          value={props.index_suffix ?? ''}
          onChange={(e) => onChange({ ...props, index_suffix: e.currentTarget.value })}
          styles={MONO}
          spellCheck={false}
        />
      </Group>
      <Group grow align="flex-start">
        <TextInput
          label="Sample regex"
          description="Optional, with a group named sample; else the file name"
          placeholder="(?P<sample>[^/]+?)\\.vcf\\.gz$"
          value={props.sample_regex ?? ''}
          onChange={(e) => onChange({ ...props, sample_regex: e.currentTarget.value })}
          styles={MONO}
          spellCheck={false}
        />
        <TextInput
          label="Sample column"
          placeholder="sample"
          value={props.sample_col ?? ''}
          onChange={(e) => onChange({ ...props, sample_col: e.currentTarget.value })}
        />
      </Group>
      <Group grow align="flex-start">
        <TextInput
          label="Assembly"
          placeholder="e.g. GRCh38"
          value={props.assembly ?? ''}
          onChange={(e) => onChange({ ...props, assembly: e.currentTarget.value })}
        />
        <NumberInput
          label="Largest file (MB)"
          description="Blank for the server default"
          min={1}
          allowDecimal={false}
          value={props.max_file_size_mb ?? ''}
          onChange={(v) =>
            onChange({ ...props, max_file_size_mb: typeof v === 'number' ? v : undefined })
          }
        />
      </Group>
    </Stack>
  );
};

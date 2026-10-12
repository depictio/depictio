/**
 * Genomic tracks properties. The collection reads a MANIFEST, a table with
 * one row per track file: its format, which of its columns hold the file,
 * the sample, the index... (picked among the manifest's columns), the
 * assembly the tracks are on (a preset of the server, or a custom one), and
 * the folder relative paths resolve against.
 *
 * Without a manifest yet, one can be generated from the track files ticked
 * in the tree (`POST /tracks_manifest`): offered as a download in server mode
 * (placed in the folder, then picked), written next to the template and used
 * straight away standalone (`POST /write_manifest`).
 */
import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  TagsInput,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  DEFAULT_FREE_ASSEMBLY,
  SPATIALDATA_FORMAT,
  apiErrorCode,
  assemblyIssue,
  builderTracksManifest,
  builderWriteManifest,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  BuilderCapabilities,
  BuilderCustomAssembly,
  BuilderGenomicTracksProps,
  BuilderRootSpec,
  BuilderTrackColumnField,
  BuilderTracksManifest,
} from 'depictio-react-core';

import type { BuilderMode } from '../../mode';
import { ColumnField, FoldSection, FormatFields, MONO } from './shared';

const CUSTOM = '__custom__';

const COLUMN_FIELDS: { field: BuilderTrackColumnField; label: string; description: string }[] = [
  { field: 'uri_column', label: 'File column', description: "Each track's file (path or URL)" },
  { field: 'sample_column', label: 'Sample column', description: 'Links and filters match on it' },
  { field: 'format_column', label: 'Format column', description: 'bigwig, bam, vcf...' },
  { field: 'index_column', label: 'Index column', description: "Each track's index file" },
  { field: 'name_column', label: 'Name column', description: 'The track label' },
  { field: 'color_column', label: 'Color column', description: 'A colour per track' },
  { field: 'category_column', label: 'Category column', description: 'Groups tracks' },
  { field: 'order_column', label: 'Order column', description: 'Sorts tracks' },
  { field: 'track_id_column', label: 'Track id column', description: 'A stable id per track' },
];

/** What the editor hands the form for a manifest it does not have yet. */
export interface ManifestTools {
  root: BuilderRootSpec;
  mode: BuilderMode;
  /** The collection's tag, to name a generated manifest. */
  tag: string;
  /** Track files ticked in the tree. */
  trackFiles: string[];
  /** The collection points at a track file, not at a manifest. */
  readsTrackFile: boolean;
  /** A downloaded manifest is awaited: the next file picked becomes it. */
  awaiting: boolean;
  /** Use `path` (relative to the data root) as the manifest, its uris
   *  relative to the data root. */
  onUseManifest: (path: string) => void;
  onAwaitManifest: () => void;
  /** Files were written: read the tree again. */
  onFilesChanged: () => void;
}

function downloadTsv(tsv: string, fileName: string): void {
  const blob = new Blob([tsv], { type: 'text/tab-separated-values;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const manifestName = (tag: string) => `${(tag.trim() || 'tracks').replace(/[^A-Za-z0-9._-]+/g, '_')}_manifest`;

/** Generate a manifest from the ticked track files, preview it, then
 *  download it (server) or write it and use it (standalone). */
const ManifestGenerator: React.FC<{ tools: ManifestTools }> = ({ tools }) => {
  const accent = useBrandAccents();
  const [sampleRegex, setSampleRegex] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<BuilderTracksManifest | null>(null);
  /** Standalone: the manifest exists (offer to replace it), or the bundle
   *  folder is outside the data root (offer the download instead). */
  const [conflict, setConflict] = useState<'exists' | 'outside' | null>(null);
  const files = tools.trackFiles;
  const name = manifestName(tools.tag);

  const generate = async () => {
    setBusy(true);
    setError(null);
    setConflict(null);
    try {
      setManifest(await builderTracksManifest(tools.root, files, sampleRegex.trim() || null));
    } catch (err) {
      setError((err as Error).message || 'The manifest could not be built.');
    } finally {
      setBusy(false);
    }
  };

  const write = async (overwrite: boolean) => {
    if (!manifest) return;
    setBusy(true);
    setError(null);
    try {
      const { path } = await builderWriteManifest(name, manifest.tsv, overwrite);
      setConflict(null);
      tools.onUseManifest(path);
      tools.onFilesChanged();
    } catch (err) {
      const code = apiErrorCode(err);
      if (code === 'manifest_exists') setConflict('exists');
      else if (code === 'manifest_outside_root') setConflict('outside');
      else setError((err as Error).message || 'The manifest could not be written.');
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    if (!manifest) return;
    downloadTsv(manifest.tsv, `${name}.tsv`);
    tools.onAwaitManifest();
  };

  const downloadRow = (
    <Group justify="space-between" wrap="nowrap" align="flex-start">
      <Text size="xs" c="dimmed">
        Place it in the folder, then pick it in the tree: it becomes this collection&apos;s manifest.
      </Text>
      <Button
        size="xs"
        color={accent.secondary}
        leftSection={<Icon icon="mdi:download" width={14} />}
        onClick={download}
        style={{ flexShrink: 0 }}
        data-testid="builder-tracks-manifest-download"
      >
        Download TSV
      </Button>
    </Group>
  );

  return (
    <Paper withBorder radius="sm" p="sm" data-testid="builder-tracks-manifest">
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text size="sm" fw={600}>
              Generate a manifest from track files
            </Text>
            <Text size="xs" c="dimmed">
              Tick the track files in the tree ({files.length} ticked), then generate a table listing
              them.
            </Text>
          </Stack>
          <Button
            size="xs"
            variant="light"
            color={accent.secondary}
            leftSection={<Icon icon="mdi:table-plus" width={14} />}
            onClick={generate}
            loading={busy && !manifest}
            disabled={files.length === 0}
            data-testid="builder-tracks-manifest-generate"
          >
            Generate
          </Button>
        </Group>
        <TextInput
          size="xs"
          label="Sample regex"
          description="Optional, with a group named sample; else the file name"
          placeholder="(?P<sample>[^/]+?)\.bw$"
          value={sampleRegex}
          onChange={(e) => setSampleRegex(e.currentTarget.value)}
          styles={MONO}
          spellCheck={false}
        />
        {error && (
          <Alert color="red" variant="light" p="xs" icon={<Icon icon="mdi:alert-circle-outline" width={14} />}>
            <Text size="xs">{error}</Text>
          </Alert>
        )}
        {manifest && (
          <>
            <ScrollArea.Autosize mah={200} type="auto">
              <Table striped withTableBorder fz="xs" data-testid="builder-tracks-manifest-preview">
                <Table.Thead>
                  <Table.Tr>
                    {manifest.columns.map((c) => (
                      <Table.Th key={c} ff="monospace">
                        {c}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {manifest.rows.slice(0, 20).map((row, i) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <Table.Tr key={i}>
                      {manifest.columns.map((c) => (
                        <Table.Td key={c} ff="monospace">
                          {row[c] ?? ''}
                        </Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
            {manifest.rows.length > 20 && (
              <Text size="xs" c="dimmed">
                The first 20 of {manifest.rows.length} rows.
              </Text>
            )}
            {manifest.warnings.map((w) => (
              <Text key={w} size="xs" c="yellow.8">
                {w}
              </Text>
            ))}
            {tools.mode === 'standalone' && conflict !== 'outside' ? (
              <Group justify="flex-end" gap="xs">
                {conflict === 'exists' && (
                  <Text size="xs" c="yellow.8" style={{ flex: 1 }}>
                    {name}.tsv already exists next to the template.
                  </Text>
                )}
                <Button
                  size="xs"
                  color={conflict === 'exists' ? 'red' : accent.secondary}
                  leftSection={<Icon icon="mdi:content-save-outline" width={14} />}
                  onClick={() => write(conflict === 'exists')}
                  loading={busy}
                  data-testid="builder-tracks-manifest-write"
                >
                  {conflict === 'exists' ? 'Replace it and use it' : 'Write it and use it'}
                </Button>
              </Group>
            ) : (
              <>
                {conflict === 'outside' && (
                  <Text size="xs" c="yellow.8">
                    The template is written outside the data folder, so the manifest cannot go next to
                    it: download it instead.
                  </Text>
                )}
                {downloadRow}
              </>
            )}
          </>
        )}
        {tools.awaiting && (
          <Group gap={6} wrap="nowrap" data-testid="builder-tracks-manifest-awaiting">
            <Icon icon="mdi:information-outline" width={14} style={{ flexShrink: 0 }} />
            <Text size="xs" c="dimmed">
              Waiting for the manifest: refresh the files, then pick it.
            </Text>
          </Group>
        )}
      </Stack>
    </Paper>
  );
};

const CustomAssemblyFields: React.FC<{
  assembly: BuilderCustomAssembly;
  onChange: (assembly: BuilderCustomAssembly) => void;
}> = ({ assembly, onChange }) => {
  const [sequence, setSequence] = useState<'twobit' | 'fasta'>(
    assembly.fasta_uri && !assembly.twobit_uri ? 'fasta' : 'twobit',
  );
  const uri = (key: keyof BuilderCustomAssembly, label: string, placeholder: string, description?: string) => (
    <TextInput
      label={label}
      description={description}
      placeholder={placeholder}
      value={(assembly[key] as string | null | undefined) ?? ''}
      onChange={(e) => onChange({ ...assembly, [key]: e.currentTarget.value })}
      styles={MONO}
      spellCheck={false}
    />
  );
  return (
    <Paper withBorder radius="sm" p="sm" data-testid="builder-props-custom-assembly">
      <Stack gap="xs">
        <Text size="xs" c="dimmed">
          Paths are relative to the data root, or https:// and s3:// locations.
        </Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          <TextInput
            label="Name"
            placeholder="e.g. dm6"
            value={assembly.name}
            onChange={(e) => onChange({ ...assembly, name: e.currentTarget.value })}
            error={!assembly.name.trim() ? 'Required' : undefined}
            data-testid="builder-props-custom-assembly-name"
          />
          <TextInput
            label="Display name"
            placeholder="Optional"
            value={assembly.display_name ?? ''}
            onChange={(e) => onChange({ ...assembly, display_name: e.currentTarget.value })}
          />
        </SimpleGrid>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Sequence
          </Text>
          <SegmentedControl
            size="xs"
            value={sequence}
            data={[
              { value: 'twobit', label: '2bit' },
              { value: 'fasta', label: 'FASTA' },
            ]}
            onChange={(v) => setSequence(v === 'fasta' ? 'fasta' : 'twobit')}
          />
        </Stack>
        {sequence === 'twobit' ? (
          uri('twobit_uri', '2bit file', 'genome/dm6.2bit')
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
            {uri('fasta_uri', 'FASTA', 'genome/dm6.fa.gz')}
            {uri('fai_uri', 'FASTA index (.fai)', 'genome/dm6.fa.gz.fai')}
            {uri('gzi_uri', 'bgzip index (.gzi)', 'genome/dm6.fa.gz.gzi', 'For a bgzipped FASTA')}
          </SimpleGrid>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          {uri('chrom_sizes_uri', 'Chromosome sizes', 'genome/dm6.chrom.sizes')}
          {uri('refname_aliases_uri', 'Reference name aliases', 'genome/aliases.txt')}
        </SimpleGrid>
        <TagsInput
          label="Aliases"
          description="Other names of this assembly (Enter to add)"
          value={assembly.aliases ?? []}
          onChange={(aliases) => onChange({ ...assembly, aliases })}
        />
      </Stack>
    </Paper>
  );
};

type BaseChoice = 'manifest' | 'root' | 'folder';

export const GenomicTracksForm: React.FC<{
  props: BuilderGenomicTracksProps;
  onChange: (props: BuilderGenomicTracksProps) => void;
  /** The manifest's columns (`/match`), else the previewed file's. */
  columns: string[];
  capabilities: BuilderCapabilities;
  tools: ManifestTools;
}> = ({ props, onChange, columns, capabilities, tools }) => {
  const accent = useBrandAccents();
  const presets = capabilities.genomic_tracks?.assemblies ?? [];
  const trackFormats = capabilities.genomic_tracks?.track_formats ?? [];
  const custom = typeof props.assembly === 'object' && props.assembly !== null;
  const presetValue = custom ? CUSTOM : (props.assembly as string) || null;
  const presetData = [
    ...(presetValue && presetValue !== CUSTOM && !presets.includes(presetValue) ? [presetValue] : []),
    ...presets,
  ];
  const assemblyError = assemblyIssue(props);
  // `''` reads as the data root, unless "another folder" was just picked
  // and its name is still to be typed.
  const [folderPicked, setFolderPicked] = useState(false);
  const basePath = props.tracks_base_path;
  let base: BaseChoice = 'manifest';
  if (typeof basePath === 'string') base = basePath.trim() || folderPicked ? 'folder' : 'root';
  const manifestFormats = capabilities.table_formats.filter((f) => f !== SPATIALDATA_FORMAT);
  const defaultFormatData = [
    ...(props.default_format && !trackFormats.includes(props.default_format) ? [props.default_format] : []),
    ...trackFormats,
  ];

  return (
    <Stack gap="xs">
      {tools.readsTrackFile && (
        <Alert
          color="yellow"
          variant="light"
          p="xs"
          icon={<Icon icon="mdi:information-outline" width={16} />}
          data-testid="builder-tracks-needs-manifest"
        >
          <Text size="xs">
            This collection reads a manifest, a table listing the track files, not a track file
            itself. Pick an existing manifest in the tree, or generate one below.
          </Text>
        </Alert>
      )}
      <FoldSection
        label="Generate a manifest from track files"
        initiallyOpen={tools.readsTrackFile || tools.awaiting}
        testId="builder-tracks-generate-section"
      >
        <ManifestGenerator tools={tools} />
      </FoldSection>

      <FormatFields
        format={props.format}
        separator={props.separator}
        formats={manifestFormats}
        label="Manifest format"
        onChange={(patch) => onChange({ ...props, ...patch })}
      />

      <Text size="sm" fw={500}>
        Manifest columns
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
        {COLUMN_FIELDS.map(({ field, label, description }) => (
          <ColumnField
            key={field}
            label={label}
            description={description}
            value={props[field] as string | null | undefined}
            columns={columns}
            placeholder={field === 'uri_column' ? 'uri' : 'None'}
            required={field === 'uri_column'}
            testId={`builder-props-tracks-${field.replace(/_column$/, '').replace(/_/g, '-')}`}
            onChange={(value) => onChange({ ...props, [field]: value })}
          />
        ))}
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
        {presets.length > 0 ? (
          <Select
            label="Assembly"
            description="The reference genome the tracks are on"
            placeholder="Pick an assembly"
            value={presetValue}
            data={[...presetData, { value: CUSTOM, label: 'Custom…' }]}
            searchable
            onChange={(v) => {
              if (v === CUSTOM) {
                onChange({ ...props, assembly: custom ? props.assembly : { name: '' } });
              } else {
                onChange({ ...props, assembly: v ?? '' });
              }
            }}
            error={!custom ? assemblyError ?? undefined : undefined}
            data-testid="builder-props-tracks-assembly"
          />
        ) : (
          <TextInput
            label="Assembly"
            description={custom ? 'A custom assembly, below' : 'A name the server knows, e.g. hg38 or mm10'}
            placeholder={DEFAULT_FREE_ASSEMBLY}
            value={custom ? 'Custom…' : (props.assembly as string)}
            disabled={custom}
            onChange={(e) => onChange({ ...props, assembly: e.currentTarget.value })}
            error={!custom ? assemblyError ?? undefined : undefined}
            rightSectionWidth={100}
            rightSectionPointerEvents="all"
            rightSection={
              <Button
                color={accent.secondary}
                size="compact-xs"
                variant="subtle"
                onClick={() =>
                  onChange({ ...props, assembly: custom ? DEFAULT_FREE_ASSEMBLY : { name: '' } })
                }
                data-testid="builder-props-tracks-assembly-custom"
              >
                {custom ? 'By name' : 'Custom…'}
              </Button>
            }
            data-testid="builder-props-tracks-assembly"
          />
        )}
        <Select
          label="Default track format"
          description="For rows without a format"
          placeholder="From each file's extension"
          value={props.default_format ?? null}
          data={defaultFormatData}
          clearable
          onChange={(v) => onChange({ ...props, default_format: v })}
          data-testid="builder-props-tracks-default-format"
        />
      </SimpleGrid>
      {custom && (
        <CustomAssemblyFields
          assembly={props.assembly as BuilderCustomAssembly}
          onChange={(assembly) => onChange({ ...props, assembly })}
        />
      )}

      <Stack gap={4}>
        <Group gap="xs">
          <Text size="sm" fw={500}>
            Relative paths resolve against
          </Text>
          {base === 'root' && (
            <Badge size="xs" variant="light" color="gray" tt="none">
              tracks_base_path: &apos;&apos;
            </Badge>
          )}
        </Group>
        <SegmentedControl
          size="xs"
          value={base}
          data={[
            { value: 'manifest', label: "The manifest's folder" },
            { value: 'root', label: 'The data root' },
            { value: 'folder', label: 'Another folder' },
          ]}
          onChange={(v) => {
            const choice = v as BaseChoice;
            setFolderPicked(choice === 'folder');
            onChange({
              ...props,
              tracks_base_path: choice === 'manifest' ? null : choice === 'root' ? '' : props.tracks_base_path || '',
            });
          }}
          data-testid="builder-props-tracks-base"
        />
        {base === 'folder' && (
          <TextInput
            placeholder="tracks/"
            description="Relative to the data root"
            value={props.tracks_base_path ?? ''}
            onChange={(e) => onChange({ ...props, tracks_base_path: e.currentTarget.value })}
            styles={MONO}
            spellCheck={false}
          />
        )}
      </Stack>
    </Stack>
  );
};

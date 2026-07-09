import { TextInput, Textarea, Stack, Title, Group, Button, Paper, Text, SimpleGrid, Code, Card, Select, Grid, Alert, Divider } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useStudioStore } from '../state/useStudioStore';
import { fetchNfCoreMeta } from '../catalog/fromNfCore';
import { findDuplicateTool, type CatalogManifest } from '../catalog/catalog';
import AddToExistingPanel from './AddToExistingPanel';
import type { NfCoreOutput, ToolSource } from '../types';

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

const BASE = import.meta.env.BASE_URL;

interface SourceMeta {
  value: ToolSource;
  label: string;
  logo: string;
  urlLabel: string;
  placeholder: string;
  /** Which module.yaml field the source URL lands in. */
  field: 'nf_core_url' | 'homepage';
  autoFetch: boolean;
}

const SOURCES: SourceMeta[] = [
  {
    value: 'nf-core',
    label: 'nf-core module',
    logo: `${BASE}logos/workflows/nf-core.png`,
    urlLabel: 'nf-core module URL',
    placeholder: 'https://github.com/nf-core/modules/tree/master/modules/nf-core/<tool>',
    field: 'nf_core_url',
    autoFetch: true,
  },
  {
    value: 'snakemake',
    label: 'Snakemake wrapper',
    logo: `${BASE}logos/workflows/snakemake.svg`,
    urlLabel: 'Snakemake wrapper URL',
    placeholder: 'https://snakemake-wrappers.readthedocs.io/en/stable/wrappers/<tool>.html',
    field: 'homepage',
    autoFetch: false,
  },
  {
    value: 'galaxy',
    label: 'Galaxy tool',
    logo: `${BASE}logos/workflows/galaxy.png`,
    urlLabel: 'Galaxy tool URL',
    placeholder: 'https://toolshed.g2.bx.psu.edu/view/<owner>/<tool>',
    field: 'homepage',
    autoFetch: false,
  },
];

export default function ToolForm({ catalog }: { catalog: CatalogManifest }) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const setTool = useStudioStore((s) => s.setTool);
  const setOutput = useStudioStore((s) => s.setOutput);
  const existing = useStudioStore((s) => s.existing);
  const setStep = useStudioStore((s) => s.setStep);
  const reset = useStudioStore((s) => s.reset);
  const [fetching, setFetching] = useState(false);
  // File output channels parsed from the last nf-core Import — populate the
  // output-channel picker so slug / path_glob / description can be auto-filled.
  const [nfOutputs, setNfOutputs] = useState<NfCoreOutput[]>([]);

  const active = SOURCES.find((s) => s.value === tool.source) ?? SOURCES[0];
  const sourceUrl = (active.field === 'nf_core_url' ? tool.nf_core_url : tool.homepage) ?? '';

  const pickSource = (value: ToolSource) => {
    // Clear both URL slots when switching so a stale URL doesn't leak across
    // sources; the field the new source writes to is chosen on next input.
    setTool({ source: value, nf_core_url: undefined, homepage: undefined });
    setNfOutputs([]);
  };

  const setSourceUrl = (url: string) => {
    setTool(active.field === 'nf_core_url' ? { nf_core_url: url } : { homepage: url });
  };

  const importFromNfCore = async () => {
    if (!sourceUrl) {
      notifications.show({ color: 'red', message: 'Paste the nf-core module URL first.' });
      return;
    }
    setFetching(true);
    try {
      const meta = await fetchNfCoreMeta(sourceUrl);
      setTool({
        id: tool.id || slugify(meta.name),
        name: tool.name || meta.name,
        description: tool.description || meta.description,
        homepage: meta.homepage,
        biotools_url: meta.biotools_url,
      });
      setNfOutputs(meta.outputs);
      const outMsg = meta.outputs.length
        ? ` — ${meta.outputs.length} output${meta.outputs.length > 1 ? 's' : ''} found, pick one on the right.`
        : ' (no file outputs found in meta.yml — fill the Output manually).';
      notifications.show({ color: 'teal', message: `Imported metadata for ${meta.name}${outMsg}` });
    } catch (e) {
      notifications.show({ color: 'red', message: `nf-core fetch failed: ${(e as Error).message}` });
    } finally {
      setFetching(false);
    }
  };

  const toolId = tool.id || '<tool>';

  const applyNfOutput = (name: string | null) => {
    const chan = nfOutputs.find((o) => o.name === name);
    if (!chan) return;
    setOutput({
      slug: slugify(chan.name),
      path_glob: `**/${toolId}/${chan.pattern}`,
      description: chan.description || output.description,
    });
  };

  // Adding to an existing tool: identity + fixture already came from the catalog,
  // so the new-tool form is replaced by a banner (the work happens on the
  // Visualizations step).
  if (existing) {
    return (
      <Stack gap="lg">
        <Alert
          color="grape"
          variant="light"
          icon={<Icon icon="mdi:playlist-plus" />}
          title={`Adding a visualization to ${existing.toolName}`}
        >
          <Text size="sm">
            Output <Code>{existing.outputSlug}</Code> — {existing.baseRenders.length} existing
            render(s). Your new visualization will append to{' '}
            <Code>{existing.yamlPath || `${existing.toolId}/${existing.outputSlug}.yaml`}</Code>.
          </Text>
          <Group mt="sm" gap="sm">
            <Button size="xs" color="grape" onClick={() => setStep(2)} rightSection={<Icon icon="mdi:chevron-right" />}>
              Continue to visualizations
            </Button>
            <Button size="xs" variant="subtle" color="gray" onClick={reset}>
              Start a new tool instead
            </Button>
          </Group>
        </Alert>
      </Stack>
    );
  }

  const duplicate = findDuplicateTool(catalog, tool);

  return (
    <Stack gap="lg">
      <AddToExistingPanel catalog={catalog} duplicate={duplicate} />
      {catalog.tools.length > 0 && <Divider label="or create a new tool" labelPosition="center" />}

      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          New tool
        </Title>
        <Text c="dimmed" size="sm">
          Identity for <Code>module.yaml</Code> and the single output this entry describes.
        </Text>
      </div>

      <Grid gutter="xl">
        {/* ── Left panel: tool identity ─────────────────────────────────── */}
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="md">
            <div>
              <Text size="sm" fw={600} mb={6}>
                Tool source
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
                {SOURCES.map((s) => {
                  const selected = s.value === tool.source;
                  return (
                    <Card
                      key={s.value}
                      withBorder
                      radius="md"
                      p="sm"
                      onClick={() => pickSource(s.value)}
                      style={{
                        cursor: 'pointer',
                        borderColor: selected ? 'var(--mantine-color-blue-filled)' : undefined,
                        borderWidth: selected ? 2 : 1,
                        background: selected ? 'var(--mantine-color-blue-light)' : undefined,
                      }}
                    >
                      <Group gap="sm" wrap="nowrap">
                        <img src={s.logo} alt={s.label} height={24} width={24} style={{ objectFit: 'contain' }} />
                        <Text fw={selected ? 700 : 500} size="sm">
                          {s.label}
                        </Text>
                      </Group>
                    </Card>
                  );
                })}
              </SimpleGrid>
            </div>

            <Paper withBorder p="md" radius="md">
              <Group align="flex-end" gap="sm" mb="sm">
                <TextInput
                  style={{ flex: 1 }}
                  label={active.urlLabel}
                  placeholder={active.placeholder}
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.currentTarget.value)}
                />
                {active.autoFetch && (
                  <Button
                    variant="light"
                    color="green"
                    loading={fetching}
                    leftSection={<Icon icon="mdi:cloud-download-outline" />}
                    onClick={importFromNfCore}
                  >
                    Import
                  </Button>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {active.autoFetch
                  ? "Fetches the module's meta.yml to pre-fill name, description, links and outputs."
                  : 'Stored as the tool homepage. Fill name & description below (auto-fetch not yet supported for this source).'}
              </Text>
            </Paper>

            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label="Tool id"
                description="lowercase slug, folder name"
                placeholder="mosdepth"
                required
                value={tool.id}
                onChange={(e) => setTool({ id: slugify(e.currentTarget.value) })}
              />
              <TextInput
                label="Tool name"
                placeholder="mosdepth"
                required
                value={tool.name}
                onChange={(e) => setTool({ name: e.currentTarget.value })}
              />
            </SimpleGrid>

            <Textarea
              label="Description (optional)"
              autosize
              minRows={2}
              value={tool.description ?? ''}
              onChange={(e) => setTool({ description: e.currentTarget.value })}
            />
          </Stack>
        </Grid.Col>

        {/* ── Right panel: output ───────────────────────────────────────── */}
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Paper withBorder p="md" radius="md" h="100%">
            <Group gap="xs" mb="xs">
              <Icon icon="mdi:file-document-outline" width={18} />
              <Title order={5}>Output</Title>
            </Group>
            <Text size="xs" c="dimmed" mb="md">
              The single file this catalog entry describes — recognized in a run by its path glob.
            </Text>

            {nfOutputs.length > 0 && (
              <Select
                label="nf-core output channel"
                description="Auto-fills slug, path glob and description from meta.yml. Editable after."
                placeholder="Pick an output to auto-fill…"
                mb="md"
                searchable
                data={nfOutputs.map((o) => ({
                  value: o.name,
                  label: `${o.name} · ${o.pattern}`,
                }))}
                onChange={applyNfOutput}
                leftSection={<Icon icon="mdi:magic-staff" width={16} />}
              />
            )}

            <Stack gap="md">
              <TextInput
                label="Output slug"
                description={`file & id → ${toolId}_${output.slug || '<slug>'}`}
                placeholder="coverage"
                required
                value={output.slug}
                onChange={(e) => setOutput({ slug: slugify(e.currentTarget.value) })}
              />
              <TextInput
                label="Path glob"
                description="how a run's file is recognized"
                placeholder="**/mosdepth/*.coverage.tsv"
                required
                value={output.path_glob}
                onChange={(e) => setOutput({ path_glob: e.currentTarget.value })}
              />
              <Textarea
                label="Output description (optional)"
                autosize
                minRows={2}
                value={output.description ?? ''}
                onChange={(e) => setOutput({ description: e.currentTarget.value })}
              />
            </Stack>
          </Paper>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

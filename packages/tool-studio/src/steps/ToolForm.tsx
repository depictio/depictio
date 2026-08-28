import { TextInput, Textarea, Stack, Title, Group, Button, Paper, Text, SimpleGrid, Code, Card, Select, Grid, Alert, Input } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useStudioStore, newOutputSlugClash } from '../state/useStudioStore';
import { fetchNfCoreMeta } from '../catalog/fromNfCore';
import { fetchSnakemakeMeta } from '../catalog/fromSnakemake';
import { fetchGalaxyMeta } from '../catalog/fromGalaxy';
import { findDuplicateTool, type CatalogManifest } from '../catalog/catalog';
import { useMultiqcModules, multiqcModuleFor } from '../catalog/multiqc';
import RecognizedTool from './RecognizedTool';
import type { ExtractedMeta, OutputChannel, ToolSource } from '../types';
import { HEADING_FONT } from '../theme';

/** Client-side metadata extractor per tool source (the one-click Import). */
const EXTRACTORS: Record<ToolSource, (url: string) => Promise<ExtractedMeta>> = {
  'nf-core': fetchNfCoreMeta,
  snakemake: fetchSnakemakeMeta,
  galaxy: fetchGalaxyMeta,
};

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

const BASE = import.meta.env.BASE_URL;

interface SourceMeta {
  value: ToolSource;
  label: string;
  /** Card copy, split so the three cards share one shape and line up: project
   *  name on line 1, artifact kind dimmed on line 2. A single `label` made
   *  "Snakemake wrapper" wrap to two lines while its neighbours stayed on one. */
  project: string;
  kind: string;
  logo: string;
  urlLabel: string;
  placeholder: string;
  /** Which module.yaml field the pasted source URL lands in. */
  field: 'nf_core_url' | 'source_url';
  autoFetch: boolean;
  /** Helper text under the URL input (source-specific fetch caveats). */
  hint: string;
}

const SOURCES: SourceMeta[] = [
  {
    value: 'nf-core',
    label: 'nf-core module',
    project: 'nf-core',
    kind: 'module',
    logo: `${BASE}logos/workflows/nf-core.png`,
    urlLabel: 'nf-core module URL',
    placeholder: 'https://github.com/nf-core/modules/tree/master/modules/nf-core/<tool>',
    field: 'nf_core_url',
    autoFetch: true,
    hint: "Fetches the module's meta.yml to pre-fill name, description, links and outputs.",
  },
  {
    value: 'snakemake',
    label: 'Snakemake wrapper',
    project: 'Snakemake',
    kind: 'wrapper',
    logo: `${BASE}logos/workflows/snakemake.svg`,
    urlLabel: 'Snakemake wrapper URL',
    placeholder: 'https://github.com/snakemake/snakemake-wrappers/tree/master/bio/<tool>',
    field: 'source_url',
    autoFetch: true,
    hint: "Fetches the wrapper's meta.yaml to pre-fill name, description and homepage. A readthedocs wrapper page works too.",
  },
  {
    value: 'galaxy',
    label: 'Galaxy tool',
    project: 'Galaxy',
    kind: 'tool',
    logo: `${BASE}logos/workflows/galaxy.png`,
    urlLabel: 'Galaxy tool URL',
    placeholder: 'https://github.com/galaxyproject/tools-iuc/blob/main/tools/<tool>/<tool>.xml',
    field: 'source_url',
    autoFetch: true,
    hint: 'Fetches the tool XML (a GitHub .xml URL) to pre-fill name, description and outputs. Fields defined via macros come back blank.',
  },
];

export default function ToolForm({ catalog }: { catalog: CatalogManifest }) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const setTool = useStudioStore((s) => s.setTool);
  const setOutput = useStudioStore((s) => s.setOutput);
  const existing = useStudioStore((s) => s.existing);
  const newOutputTarget = useStudioStore((s) => s.newOutputTarget);
  const setStep = useStudioStore((s) => s.setStep);
  const reset = useStudioStore((s) => s.reset);
  // The catalog tool id the author has dismissed as "not my tool", so the
  // recognized panel yields to new-tool authoring until the identity changes to
  // a *different* match. Held in the store so a Back/Next round-trip (which
  // unmounts this step) doesn't resurface a dismissed match.
  const dismissedMatchId = useStudioStore((s) => s.dismissedMatchId);
  const setDismissedMatch = useStudioStore((s) => s.setDismissedMatch);
  const multiqcModules = useMultiqcModules();
  const [fetching, setFetching] = useState(false);
  // File output channels parsed from the last Import — populate the
  // output-channel picker so slug / path_glob / description can be auto-filled.
  const [extractedOutputs, setExtractedOutputs] = useState<OutputChannel[]>([]);

  const active = SOURCES.find((s) => s.value === tool.source) ?? SOURCES[0];
  const sourceUrl = (active.field === 'nf_core_url' ? tool.nf_core_url : tool.source_url) ?? '';

  const pickSource = (value: ToolSource) => {
    // Full identity reset when switching source, so a name/id/link from the
    // previous source can't linger (a Snakemake "samtools" must not survive a
    // switch to Galaxy). The author re-imports or retypes for the new source.
    setTool({
      source: value,
      id: '',
      name: '',
      description: undefined,
      nf_core_url: undefined,
      source_url: undefined,
      homepage: undefined,
      biotools_url: undefined,
    });
    setExtractedOutputs([]);
  };

  const setSourceUrl = (url: string) => {
    setTool(active.field === 'nf_core_url' ? { nf_core_url: url } : { source_url: url });
  };

  const importMeta = async () => {
    if (!sourceUrl) {
      notifications.show({ color: 'red', message: `Paste the ${active.label} URL first.` });
      return;
    }
    setFetching(true);
    try {
      const meta = await EXTRACTORS[tool.source](sourceUrl);
      setTool({
        // Import is an explicit "pull metadata" action, so fetched values win
        // over whatever is in the form (a stale name from a previous source, or
        // a re-import of a different URL). Fields the source doesn't declare are
        // cleared rather than left stale.
        id: meta.name ? slugify(meta.name) : tool.id,
        name: meta.name || tool.name,
        description: meta.description || undefined,
        // nf-core keeps its URL in nf_core_url (canonicalised on export); other
        // sources record the fetched location in source_url — normalise the
        // pasted value to the GitHub form that was actually fetched.
        ...(tool.source !== 'nf-core' ? { source_url: meta.source_url } : {}),
        homepage: meta.homepage || undefined,
        biotools_url: meta.biotools_url || undefined,
      });
      setExtractedOutputs(meta.outputs);
      const outMsg = meta.outputs.length
        ? `: ${meta.outputs.length} output${meta.outputs.length > 1 ? 's' : ''} found, pick one on the right.`
        : ' (no file outputs found, fill the Output manually).';
      notifications.show({ color: 'accent', message: `Imported metadata for ${meta.name}${outMsg}` });
    } catch (e) {
      notifications.show({
        color: 'red',
        message: `${active.label} fetch failed: ${(e as Error).message}`,
      });
    } finally {
      setFetching(false);
    }
  };

  const toolId = tool.id || '<tool>';

  const applyOutput = (name: string | null) => {
    const chan = extractedOutputs.find((o) => o.name === name);
    if (!chan) return;
    setOutput({
      slug: slugify(chan.name),
      // Some sources (Snakemake) describe outputs in prose with no glob — leave
      // path_glob for the author to complete rather than emit a dangling `**/`.
      path_glob: chan.pattern ? `**/${toolId}/${chan.pattern}` : output.path_glob,
      description: chan.description || output.description,
    });
  };

  // ── Reusable field groups (shared across the entry branches) ───────────────
  // Identity and Output are the two halves of this step and sit side by side, so
  // they are built from the same parts: one bordered panel of equal height, an
  // icon + Title order={5} header, a dimmed one-line summary, then a Stack of
  // fields that all carry a Mantine label + description. Anything added to one
  // side should keep that shape, or the two columns stop reading as a pair.
  const identityFields = (
    <Paper withBorder p="md" radius="md" h="100%">
      <Group gap="xs" mb="xs">
        <Icon icon="mdi:tag-outline" width={18} />
        <Title order={5}>Identity</Title>
      </Group>
      <Text size="xs" c="dimmed" mb="md">
        Which tool this catalog entry belongs to, and where its metadata is imported from.
      </Text>

      <Stack gap="md">
      <Input.Wrapper label="Tool source" description="where Import pulls the metadata from">
        <SimpleGrid
          mt={6}
          cols={{ base: 1, sm: 3 }}
          spacing="sm"
          role="radiogroup"
          aria-label="Tool source"
        >
          {SOURCES.map((s) => {
            const selected = s.value === tool.source;
            return (
              <Card
                key={s.value}
                withBorder
                radius="md"
                p="sm"
                // A real radio: the source picker was a div with an onClick, so
                // it could not be reached or activated from the keyboard at all.
                component="button"
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={s.label}
                onClick={() => pickSource(s.value)}
                style={{
                  cursor: 'pointer',
                  width: '100%',
                  textAlign: 'left',
                  font: 'inherit',
                  color: 'inherit',
                  borderColor: selected ? 'var(--mantine-primary-color-filled)' : undefined,
                  borderWidth: selected ? 2 : 1,
                  background: selected ? 'var(--mantine-primary-color-light)' : undefined,
                }}
              >
                <Group gap="sm" wrap="nowrap">
                  <img src={s.logo} alt="" height={24} width={24} style={{ objectFit: 'contain' }} />
                  <div style={{ lineHeight: 1.15, minWidth: 0 }}>
                    <Text fw={selected ? 700 : 500} size="sm" style={{ whiteSpace: 'nowrap' }}>
                      {s.project}
                    </Text>
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                      {s.kind}
                    </Text>
                  </div>
                </Group>
              </Card>
            );
          })}
        </SimpleGrid>
      </Input.Wrapper>

      {/* The URL + Import row used to be its own bordered Paper. Inside this
          panel that read as a card within a card, so the hint became the
          input's `description` like every other field here. */}
      <Group align="flex-end" gap="sm" wrap="nowrap">
        <TextInput
          style={{ flex: 1 }}
          label={active.urlLabel}
          description={active.hint}
          placeholder={active.placeholder}
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.currentTarget.value)}
        />
        {active.autoFetch && (
          <Button
            variant="light"
            loading={fetching}
            leftSection={<Icon icon="mdi:cloud-download-outline" />}
            onClick={importMeta}
          >
            Import
          </Button>
        )}
      </Group>

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
          description="display name, shown in the catalog"
          placeholder="mosdepth"
          required
          value={tool.name}
          onChange={(e) => setTool({ name: e.currentTarget.value })}
        />
      </SimpleGrid>

      <Textarea
        label="Tool description (optional)"
        autosize
        minRows={2}
        value={tool.description ?? ''}
        onChange={(e) => setTool({ description: e.currentTarget.value })}
      />
      </Stack>
    </Paper>
  );

  const outputFields = (slugError?: string) => (
    <Paper withBorder p="md" radius="md" h="100%">
      <Group gap="xs" mb="xs">
        <Icon icon="mdi:file-document-outline" width={18} />
        <Title order={5}>Output</Title>
      </Group>
      <Text size="xs" c="dimmed" mb="md">
        The single file this catalog entry describes, recognized in a run by its path glob.
      </Text>

      {extractedOutputs.length > 0 && (
        <Select
          label="Output channel"
          description="Auto-fills slug, path glob and description from the source metadata. Editable after."
          placeholder="Pick an output to auto-fill…"
          mb="md"
          searchable
          data={extractedOutputs.map((o) => ({
            value: o.name,
            label: o.pattern ? `${o.name} · ${o.pattern}` : `${o.name} · (set path glob)`,
          }))}
          onChange={applyOutput}
          leftSection={<Icon icon="mdi:magic-staff" width={16} />}
        />
      )}

      <Stack gap="md">
        <TextInput
          label="Output slug"
          description={`file & id → ${toolId}_${output.slug || '<slug>'}`}
          placeholder="coverage"
          required
          error={slugError}
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
  );

  // ── Branch A — adding a visualization to an existing output (append mode) ──
  // Identity + fixture already came from the catalog, so the form is replaced by
  // a banner (the work happens on the Visualizations step).
  if (existing) {
    return (
      <Stack gap="lg">
        <Alert
          color="brand"
          variant="light"
          icon={<Icon icon="mdi:playlist-plus" />}
          title={`Adding a visualization to ${existing.toolName}`}
        >
          <Text size="sm">
            Output <Code>{existing.outputSlug}</Code>, {existing.baseRenders.length} existing
            render(s). Your new visualization will append to{' '}
            <Code>{existing.yamlPath || `${existing.toolId}/${existing.outputSlug}.yaml`}</Code>.
          </Text>
          <Group mt="sm" gap="sm">
            <Button size="xs" color="brand" onClick={() => setStep(2)} rightSection={<Icon icon="mdi:chevron-right" />}>
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

  // ── Branch B — adding a NEW output to an existing tool ─────────────────────
  // Identity is locked to the catalog tool; the author writes a fresh output
  // (slug/path_glob) here, then brings its own fixture + renders.
  if (newOutputTarget) {
    const slugClash = newOutputSlugClash(newOutputTarget, output.slug);
    return (
      <Stack gap="lg">
        <Alert
          color="accent"
          variant="light"
          icon={<Icon icon="mdi:file-plus-outline" />}
          title={`Adding a new output to ${newOutputTarget.toolName}`}
        >
          <Text size="sm">
            Reuses the tool's identity; export writes a new{' '}
            <Code>
              {newOutputTarget.dir}/{output.slug || '<slug>'}.yaml
            </Code>{' '}
            (+ its fixture). <Code>module.yaml</Code> is left untouched.
          </Text>
          <Group mt="sm">
            <Button size="xs" variant="subtle" color="gray" onClick={reset}>
              Start a new tool instead
            </Button>
          </Group>
        </Alert>

        {outputFields(
          slugClash
            ? `${output.slug} already exists on ${newOutputTarget.toolName}, pick a different slug`
            : undefined,
        )}
      </Stack>
    );
  }

  // ── Branch C — recognition-first entry ─────────────────────────────────────
  const duplicate = findDuplicateTool(catalog, tool);
  const match = duplicate && duplicate.tool.id !== dismissedMatchId ? duplicate : null;

  const header = (
    <div>
      <Title order={3} style={{ fontFamily: HEADING_FONT, fontWeight: 600 }}>
        Tool
      </Title>
      <Text c="dimmed" size="sm">
        Name the tool and the output file this entry describes. As you type we check the catalog:
        if the tool is already there, you can add to it instead of starting a new entry.
      </Text>
    </div>
  );

  // MultiQC already parses this tool: its metrics normally reach depictio
  // through the MultiQC integration, so a hand-authored entry duplicates work
  // that already exists. A warning, never a block: an output MultiQC skips (or
  // reports less richly than the raw file) is a good reason to carry on.
  const multiqcModule = multiqcModuleFor(multiqcModules, tool);
  const multiqcWarning = multiqcModule && (
    <Alert
      color="yellow"
      variant="light"
      icon={<Icon icon="mdi:alert-outline" />}
      title={`MultiQC already parses ${multiqcModule}`}
    >
      <Text size="sm">
        MultiQC ships a <Code>{multiqcModule}</Code> module, so this tool's metrics usually reach
        depictio through the MultiQC integration, with no catalog entry to author. Continue only if
        you need an output MultiQC does not cover, or more of the file than its general-stats row.
      </Text>
    </Alert>
  );

  // A recognized tool: identity full-width, the existing entry + its two actions
  // below (routing supersedes new-output authoring).
  if (match) {
    return (
      <Stack gap="lg">
        {header}
        {multiqcWarning}
        {identityFields}
        <RecognizedTool
          tool={match.tool}
          reason={match.reason}
          onDismiss={() => setDismissedMatch(match.tool.id)}
        />
      </Stack>
    );
  }

  // No match → author a brand-new tool (identity + its single output).
  return (
    <Stack gap="lg">
      {header}
      {multiqcWarning}
      <Grid gutter="xl">
        <Grid.Col span={{ base: 12, md: 6 }}>{identityFields}</Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>{outputFields()}</Grid.Col>
      </Grid>
    </Stack>
  );
}

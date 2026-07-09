import { useMemo, useState } from 'react';
import { Alert, Button, Group, Paper, Select, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useStudioStore } from '../state/useStudioStore';
import type { CatalogManifest, DuplicateMatch, ManifestTool } from '../catalog/catalog';

const renderCount = (tool: ManifestTool) =>
  tool.outputs.reduce((n, o) => n + (o.renders_as?.length ?? 0), 0);

/**
 * Tool step add-on: (1) a warning when the in-progress tool duplicates one
 * already in the catalog, and (2) a picker to add a visualization to an
 * existing tool/output instead of authoring a new tool. Both funnel into
 * `startExisting`, which loads the tool's identity + fixture and jumps to the
 * Visualizations step.
 */
export default function AddToExistingPanel({
  catalog,
  duplicate,
}: {
  catalog: CatalogManifest;
  duplicate: DuplicateMatch | null;
}) {
  const startExisting = useStudioStore((s) => s.startExisting);
  // Seed the picker from a detected duplicate so "add to it instead" pre-selects.
  const [toolId, setToolId] = useState<string | null>(duplicate?.tool.id ?? null);
  const [outputId, setOutputId] = useState<string | null>(null);

  const tool = useMemo(() => catalog.tools.find((t) => t.id === toolId) ?? null, [catalog, toolId]);
  // Auto-pick the sole output; otherwise honor the explicit choice.
  const chosenOutputId = tool && tool.outputs.length === 1 ? tool.outputs[0].id : outputId;
  const output = tool?.outputs.find((o) => o.id === chosenOutputId) ?? null;

  if (!catalog.tools.length) return null;

  const go = () => {
    if (tool && output) startExisting(tool, output);
  };

  const selectTool = (id: string | null) => {
    setToolId(id);
    setOutputId(null);
  };

  return (
    <>
      {duplicate && (
        <Alert
          color="orange"
          variant="light"
          icon={<Icon icon="mdi:alert" />}
          title={`"${duplicate.tool.name}" is already in the catalog`}
        >
          <Text size="sm">
            It matches by {duplicate.reason} — {duplicate.tool.outputs.length} output(s),{' '}
            {renderCount(duplicate.tool)} render(s). Add your visualization to it instead of creating
            a duplicate tool.
          </Text>
        </Alert>
      )}

      <Paper withBorder radius="md" p="md" bg="var(--app-subtle-bg)">
        <Group gap="sm" mb="sm" wrap="nowrap">
          <ThemeIcon variant="light" color="grape" radius="md" size={34}>
            <Icon icon="mdi:playlist-plus" width={20} />
          </ThemeIcon>
          <div>
            <Text fw={600} size="sm">
              Add a visualization to an existing tool
            </Text>
            <Text size="xs" c="dimmed">
              Reuses the tool's identity + fixture; your new render appends to its{' '}
              <code>renders_as</code>.
            </Text>
          </div>
        </Group>
        <Group align="flex-end" gap="sm" grow>
          <Select
            label="Tool"
            placeholder="Pick a catalog tool…"
            searchable
            value={toolId}
            onChange={selectTool}
            data={catalog.tools.map((t) => ({ value: t.id, label: `${t.name} (${t.id})` }))}
          />
          <Select
            label="Output"
            placeholder={tool ? 'Pick an output…' : 'Pick a tool first'}
            searchable
            disabled={!tool || tool.outputs.length <= 1}
            value={chosenOutputId}
            onChange={setOutputId}
            data={(tool?.outputs ?? []).map((o) => ({
              value: o.id,
              label: `${o.slug} · ${o.renders_as?.length ?? 0} render(s)`,
            }))}
          />
        </Group>
        <Group justify="flex-end" mt="sm">
          <Button
            color="grape"
            disabled={!output}
            leftSection={<Icon icon="mdi:plus" />}
            onClick={go}
          >
            Add visualization
          </Button>
        </Group>
      </Paper>
    </>
  );
}

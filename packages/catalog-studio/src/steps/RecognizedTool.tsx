import { Alert, Badge, Button, Divider, Group, Paper, Stack, Text, ThemeIcon, Anchor } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useStudioStore } from '../state/useStudioStore';
import type { DuplicateReason, ManifestRender, ManifestTool } from '../catalog/catalog';

/** Short label for an existing render badge — the most specific of kind /
 *  visu_type / component. */
const renderLabel = (r: ManifestRender) => r.kind || r.visu_type || r.component;

/**
 * Recognition-first result: shown on the Tool step when the in-progress identity
 * matches a catalog tool. Surfaces the existing entry read-only (outputs + their
 * renders) and routes the two ways to extend it — add a visualization to an
 * existing output (`startExisting`) or add a brand-new output to the tool
 * (`startNewOutput`) — plus an escape hatch back to new-tool authoring.
 */
export default function RecognizedTool({
  tool,
  reason,
  onDismiss,
}: {
  tool: ManifestTool;
  reason: DuplicateReason;
  onDismiss: () => void;
}) {
  const startExisting = useStudioStore((s) => s.startExisting);
  const startNewOutput = useStudioStore((s) => s.startNewOutput);

  return (
    <Paper withBorder radius="md" p="md" bg="var(--app-subtle-bg)">
      <Group gap="sm" mb="xs" wrap="nowrap">
        <ThemeIcon variant="light" color="teal" radius="md" size={34}>
          <Icon icon="mdi:check-decagram" width={20} />
        </ThemeIcon>
        <div>
          <Text fw={600} size="sm">
            <strong>{tool.name}</strong> is already in the catalog
          </Text>
          <Text size="xs" c="dimmed">
            Matched by {reason}. Add your visualization to an existing output, or add a new output to
            this tool.
          </Text>
        </div>
      </Group>

      <Stack gap="sm" mt="sm">
        {tool.outputs.map((output) => {
          const renders = output.renders_as ?? [];
          return (
            <Alert
              key={output.id}
              color="grape"
              variant="light"
              p="sm"
              icon={<Icon icon="mdi:file-document-outline" />}
              // Stable hook for the e2e: the visible label is just the slug, and
              // several outputs share substrings.
              data-output={output.slug}
            >
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
                <div style={{ minWidth: 0 }}>
                  <Text fw={600} size="sm">
                    {output.slug}
                  </Text>
                  {output.description && (
                    <Text size="xs" c="dimmed" lineClamp={2}>
                      {output.description}
                    </Text>
                  )}
                  <Group gap={4} mt={6}>
                    {renders.length === 0 ? (
                      <Text size="xs" c="dimmed" fs="italic">
                        no renders yet
                      </Text>
                    ) : (
                      renders.map((r, i) => (
                        <Badge key={r.id ?? i} variant="light" color="grape" size="sm" radius="sm">
                          {renderLabel(r)}
                        </Badge>
                      ))
                    )}
                  </Group>
                </div>
                <Button
                  size="xs"
                  color="grape"
                  variant="light"
                  style={{ flexShrink: 0 }}
                  leftSection={<Icon icon="mdi:plus" />}
                  onClick={() => startExisting(tool, output)}
                >
                  Add a visualization here
                </Button>
              </Group>
            </Alert>
          );
        })}
      </Stack>

      <Divider my="md" />

      <Group justify="space-between" wrap="nowrap">
        <Button
          color="teal"
          variant="light"
          leftSection={<Icon icon="mdi:file-plus-outline" />}
          onClick={() => startNewOutput(tool)}
        >
          Add a new output to this tool
        </Button>
        <Anchor component="button" type="button" size="xs" c="dimmed" onClick={onDismiss}>
          Not this tool? Continue as a new tool
        </Anchor>
      </Group>
    </Paper>
  );
}

import { useState } from 'react';
import {
  Stack,
  Title,
  Text,
  Button,
  Group,
  Card,
  Code,
  Tabs,
  Alert,
  Badge,
  ThemeIcon,
  ActionIcon,
  Paper,
  TextInput,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { useStudioStore } from '../state/useStudioStore';
import { validateRender } from '../catalog/grounding';
import { renderToSnippet, outputId } from '../catalog/yamlGen';
import { metaFor, variantOf, bindsOf } from '../viz/renderMeta';
import VizPreview from '../viz/VizPreview';
import AddComponentModal from '../builder/AddComponentModal';
import type { KindsMap, ParsedFixture, RenderSpec } from '../types';

const slugify = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

/** One added visualization, styled like the Tools Catalog `ComponentCard`
 *  (colored type icon + name/variant + render index, role→column binds, a
 *  collapsible `renders_as` snippet, and the live preview). */
function RenderCard({
  render,
  index,
  fileName,
  toolId,
  fixture,
  kinds,
  onRemove,
  onUpdate,
}: {
  render: RenderSpec;
  index: string;
  fileName: string;
  toolId: string;
  fixture: ParsedFixture;
  kinds: KindsMap;
  onRemove: () => void;
  onUpdate: (patch: Partial<RenderSpec>) => void;
}) {
  const meta = metaFor(render.component);
  const variant = variantOf(render, kinds);
  const binds = bindsOf(render);
  const issues = validateRender(render, fixture.columns, kinds);
  const errors = issues.filter((i) => i.severity === 'error');

  return (
    <Card withBorder radius="md" shadow="sm" p="md">
      <Group justify="space-between" mb="xs" wrap="nowrap" align="flex-start">
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon size={42} radius="md" variant="light" color={meta.color}>
            <Icon icon={meta.icon} width={24} />
          </ThemeIcon>
          <div>
            <Text fz="lg" fw={700}>
              {meta.name}
              {variant && (
                <Text span c="dimmed" fw={400}>
                  {' · '}
                  {variant}
                </Text>
              )}
            </Text>
            <Code fz="xs" c="dimmed" bg="transparent">
              {index}
            </Code>
          </div>
        </Group>
        <Group gap="xs" wrap="nowrap">
          {errors.length > 0 && (
            <Badge color="red" variant="light" size="sm">
              {errors.length} issue{errors.length > 1 ? 's' : ''}
            </Badge>
          )}
          <ActionIcon variant="subtle" color="red" onClick={onRemove} aria-label="Remove">
            <Icon icon="mdi:trash-can-outline" />
          </ActionIcon>
        </Group>
      </Group>

      {binds.length > 0 && (
        <Group gap="xs" mb="xs" align="center">
          <Text fz="xs" fw={700} c="dimmed" tt="uppercase">
            Binds
          </Text>
          {binds.map(([role, col]) => (
            <Badge key={role} size="sm" variant="light" color="gray" radius="sm">
              {role} → {col}
            </Badge>
          ))}
        </Group>
      )}

      {/* Two sections: the user-facing preview and the developer-facing catalog
          YAML (identical to what's written to <output>.yaml under renders_as). */}
      <Tabs defaultValue="preview" variant="outline">
        <Tabs.List>
          <Tabs.Tab value="preview" leftSection={<Icon icon="tabler:eye" width={14} />}>
            Preview
          </Tabs.Tab>
          <Tabs.Tab value="yaml" leftSection={<Icon icon="mdi:code-braces" width={14} />}>
            Developer
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="preview" pt="sm">
          <Text size="xs" c="dimmed" mb={6}>
            How this renders for users on the dashboard.
          </Text>
          <Paper withBorder radius="sm" p="xs" bg="var(--app-subtle-bg)">
            <VizPreview fixture={fixture} render={render} kinds={kinds} height={280} />
          </Paper>
          {issues.length > 0 && (
            <Stack gap={4} mt="sm">
              {issues.map((i, k) => (
                <Text key={k} size="xs" c={i.severity === 'error' ? 'red' : 'orange'}>
                  <Icon
                    icon={i.severity === 'error' ? 'mdi:alert-circle' : 'mdi:alert'}
                    width={12}
                    style={{ verticalAlign: 'middle' }}
                  />{' '}
                  {i.message}
                </Text>
              ))}
            </Stack>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="yaml" pt="sm">
          <TextInput
            label="Render id (optional)"
            description="A unique handle so a dashboard can reuse this render via use:"
            placeholder={slugify(variant || meta.name)}
            value={render.id ?? ''}
            onChange={(e) => onUpdate({ id: slugify(e.currentTarget.value) || undefined })}
            leftSection={<Icon icon="mdi:identifier" width={14} />}
            size="xs"
            mb="sm"
          />
          <Text size="xs" c="dimmed" mb={6}>
            Catalog definition — written into <Code fz="xs">{fileName}</Code> under{' '}
            <Code fz="xs">renders_as</Code>:
          </Text>
          <CodeHighlight code={renderToSnippet(render)} language="yaml" withCopyButton />
          {render.id && (
            <>
              <Text size="xs" c="dimmed" mt="md" mb={6}>
                Dashboard reuse — drop this component into a dashboard and point it at your data
                collection:
              </Text>
              <CodeHighlight
                code={[
                  `- use: ${toolId}/${render.id}`,
                  `  component_type: ${render.component}`,
                  `  workflow_tag: <your-workflow>`,
                  `  data_collection_tag: <your-data-collection>`,
                ].join('\n')}
                language="yaml"
                withCopyButton
              />
              {render.component !== 'advanced_viz' && (
                <Text c="dimmed" mt={4} style={{ fontSize: 10 }}>
                  Note: depictio currently resolves <Code fz="xs">use:</Code> for advanced_viz renders;
                  broader component support is planned.
                </Text>
              )}
            </>
          )}
        </Tabs.Panel>
      </Tabs>
    </Card>
  );
}

export default function VizDesigner({ kinds }: { kinds: KindsMap }) {
  const fixture = useStudioStore((s) => s.fixture);
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const renders = useStudioStore((s) => s.renders);
  const addRender = useStudioStore((s) => s.addRender);
  const removeRender = useStudioStore((s) => s.removeRender);
  const updateRender = useStudioStore((s) => s.updateRender);
  const [modalOpen, setModalOpen] = useState(false);

  if (!fixture) return <Text c="dimmed">Drop a fixture first.</Text>;

  const baseId = outputId(tool.id || 'tool', output.slug || 'output');
  const fileName = `${output.slug || 'output'}.yaml`;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
            Visualizations
          </Title>
          <Text c="dimmed" size="sm">
            Add dashboard components with depictio's component builder. Each card mirrors how it
            appears in the depictio Tools Catalog.
          </Text>
        </div>
        <Button leftSection={<Icon icon="mdi:plus" />} color="blue" onClick={() => setModalOpen(true)}>
          Add visualization
        </Button>
      </Group>

      {renders.length === 0 && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          No visualizations yet. Add at least one to continue.
        </Alert>
      )}

      <Stack gap="md">
        {renders.map((render, i) => (
          <RenderCard
            key={render.uid}
            render={render}
            index={`${baseId}-${i}`}
            fileName={fileName}
            toolId={tool.id || 'tool'}
            fixture={fixture}
            kinds={kinds}
            onRemove={() => removeRender(render.uid)}
            onUpdate={(patch) => updateRender(render.uid, patch)}
          />
        ))}
      </Stack>

      <AddComponentModal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        fixture={fixture}
        kinds={kinds}
        onAdd={addRender}
      />
    </Stack>
  );
}

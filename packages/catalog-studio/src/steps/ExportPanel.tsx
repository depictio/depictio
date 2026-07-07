import { useMemo, useState } from 'react';
import { Stack, Title, Text, Button, Group, Paper, Alert, Tabs, Code, Badge } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import JSZip from 'jszip';
import { useStudioStore } from '../state/useStudioStore';
import { generateEntry } from '../catalog/yamlGen';
import { validateAll } from '../catalog/grounding';
import type { KindsMap } from '../types';
import PrModal from './PrModal';

export default function ExportPanel({ kinds }: { kinds: KindsMap }) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const [prOpen, setPrOpen] = useState(false);

  const entry = useMemo(() => {
    if (!fixture) return null;
    return generateEntry({
      tool,
      output,
      fixtureFileName: fixture.fileName,
      fixtureContent: fixture.raw,
      renders,
    });
  }, [tool, output, fixture, renders]);

  const issues = fixture ? validateAll(renders, fixture.columns, kinds) : [];
  const errors = issues.filter((i) => i.severity === 'error');

  if (!fixture || !entry) return <Text c="dimmed">Complete the earlier steps first.</Text>;

  const downloadZip = async () => {
    const zip = new JSZip();
    const dir = zip.folder(tool.id)!;
    dir.file('module.yaml', entry.moduleYaml);
    dir.file(entry.outputYamlName, entry.outputYaml);
    dir.file(entry.fixtureName, entry.fixtureContent);
    const blob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tool.id}-catalog.zip`;
    a.click();
    URL.revokeObjectURL(url);
    notifications.show({ color: 'teal', message: `Downloaded ${tool.id}-catalog.zip` });
  };

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Export
        </Title>
        <Text c="dimmed" size="sm">
          Download a zip to drop into <Code>depictio/catalog/{tool.id}/</Code>, or open a PR
          directly. CI (<Code>dev catalog validate</Code>) is the authoritative check.
        </Text>
      </div>

      {errors.length > 0 ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />} title={`${errors.length} grounding error(s)`}>
          <Stack gap={2}>
            {errors.map((e, i) => (
              <Text key={i} size="sm">
                {e.message}
              </Text>
            ))}
          </Stack>
          <Text size="xs" c="dimmed" mt="xs">
            You can still export, but CI will reject these until fixed.
          </Text>
        </Alert>
      ) : (
        <Alert color="teal" variant="light" icon={<Icon icon="mdi:check-circle-outline" />}>
          Client checks pass — {renders.length} render(s) grounded against{' '}
          <Badge variant="light" size="sm">
            {fixture.fileName}
          </Badge>
          .
        </Alert>
      )}

      <Group>
        <Button size="md" color="green" leftSection={<Icon icon="mdi:folder-zip-outline" />} onClick={downloadZip}>
          Download zip
        </Button>
        <Button
          size="md"
          variant="light"
          leftSection={<Icon icon="mdi:source-pull" />}
          onClick={() => setPrOpen(true)}
        >
          Open a pull request…
        </Button>
      </Group>

      <Paper withBorder radius="md" p="md">
        <Tabs defaultValue="module">
          <Tabs.List>
            <Tabs.Tab value="module" leftSection={<Icon icon="mdi:file-cog-outline" />}>
              module.yaml
            </Tabs.Tab>
            <Tabs.Tab value="output" leftSection={<Icon icon="mdi:file-chart-outline" />}>
              {entry.outputYamlName}
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="module" pt="sm">
            <CodeHighlight code={entry.moduleYaml} language="yaml" />
          </Tabs.Panel>
          <Tabs.Panel value="output" pt="sm">
            <CodeHighlight code={entry.outputYaml} language="yaml" />
          </Tabs.Panel>
        </Tabs>
      </Paper>

      <PrModal opened={prOpen} onClose={() => setPrOpen(false)} entry={entry} />
    </Stack>
  );
}

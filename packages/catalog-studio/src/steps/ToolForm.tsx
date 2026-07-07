import { TextInput, Textarea, Stack, Title, Group, Button, Paper, Text, SimpleGrid, Code } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useStudioStore } from '../state/useStudioStore';
import { fetchNfCoreMeta } from '../catalog/fromNfCore';

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

export default function ToolForm() {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const setTool = useStudioStore((s) => s.setTool);
  const setOutput = useStudioStore((s) => s.setOutput);
  const [fetching, setFetching] = useState(false);

  const importFromNfCore = async () => {
    if (!tool.nf_core_url) {
      notifications.show({ color: 'red', message: 'Paste an nf-core module URL first.' });
      return;
    }
    setFetching(true);
    try {
      const meta = await fetchNfCoreMeta(tool.nf_core_url);
      setTool({
        id: tool.id || slugify(meta.name),
        name: tool.name || meta.name,
        description: tool.description || meta.description,
        homepage: meta.homepage,
        biotools_url: meta.biotools_url,
      });
      notifications.show({ color: 'teal', message: `Imported metadata for ${meta.name}.` });
    } catch (e) {
      notifications.show({ color: 'red', message: `nf-core fetch failed: ${(e as Error).message}` });
    } finally {
      setFetching(false);
    }
  };

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          New tool
        </Title>
        <Text c="dimmed" size="sm">
          Identity for <Code>module.yaml</Code> and the single output this entry describes.
        </Text>
      </div>

      <Paper withBorder p="md" radius="md">
        <Group align="flex-end" gap="sm" mb="sm">
          <TextInput
            style={{ flex: 1 }}
            label="nf-core module URL (optional)"
            placeholder="https://github.com/nf-core/modules/tree/master/modules/nf-core/<tool>"
            value={tool.nf_core_url ?? ''}
            onChange={(e) => setTool({ nf_core_url: e.currentTarget.value })}
          />
          <Button
            variant="light"
            color="green"
            loading={fetching}
            leftSection={<Icon icon="mdi:cloud-download-outline" />}
            onClick={importFromNfCore}
          >
            From nf-core
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          Fetches the module's <Code>meta.yml</Code> to pre-fill name, description and links.
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

      <Paper withBorder p="md" radius="md">
        <Title order={5} mb="xs">
          Output
        </Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label="Output slug"
            description={`file & id → ${tool.id || '<tool>'}_${output.slug || '<slug>'}`}
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
        </SimpleGrid>
        <Textarea
          mt="sm"
          label="Output description (optional)"
          autosize
          minRows={1}
          value={output.description ?? ''}
          onChange={(e) => setOutput({ description: e.currentTarget.value })}
        />
      </Paper>
    </Stack>
  );
}

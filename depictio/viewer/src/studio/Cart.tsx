/**
 * Bottom bar: the "cart" of Data Collections + attached visus, the output-mode
 * toggle (Dashboard | Tool catalogue — the latter deferred/disabled), and Export.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Code,
  Group,
  Modal,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { exportDashboard, type ExportResult } from './backend';
import { toLiteComponent, type CartItem } from './spec';

interface Props {
  items: CartItem[];
  onRemove: (id: string) => void;
}

function download(name: string, content: string) {
  const blob = new Blob([content], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function dcTagForFile(file: string): string {
  const stem = file.split('/').pop()!.replace(/\.[^.]+$/, '');
  return stem.replace(/[^a-zA-Z0-9_]+/g, '_').toLowerCase() || 'data';
}

const Cart: React.FC<Props> = ({ items, onRemove }) => {
  const [mode, setMode] = useState<'dashboard' | 'catalog'>('dashboard');
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const dcTags = Array.from(new Set(items.map((i) => i.dcTag)));

  const doExport = async () => {
    setBusy(true);
    setError(null);
    try {
      const files: Record<string, string> = {};
      for (const it of items) files[it.dcTag] = it.file;
      const data_collections = dcTags.map((tag) => ({ dc_tag: tag, path: files[tag], mode: 'single' }));
      const components = items.map((it) => toLiteComponent(it.spec, it.dcTag));
      const res = await exportDashboard({
        name: 'Depictio Studio Project',
        title: 'Depictio Studio Dashboard',
        data_collections,
        components,
      });
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box
      px="md"
      py="xs"
      style={{ borderTop: '1px solid var(--mantine-color-default-border)', background: 'var(--mantine-color-default)' }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="wrap" style={{ minWidth: 0 }}>
          <Text size="sm" fw={600}>
            <Icon icon="mdi:cart-outline" width={16} style={{ verticalAlign: -3 }} /> Cart
          </Text>
          {dcTags.length === 0 ? (
            <Text size="sm" c="dimmed">
              Add visualizations to build a dashboard.
            </Text>
          ) : (
            dcTags.map((tag) => (
              <Badge key={tag} variant="light" radius="sm" tt="none">
                {tag} · {items.filter((i) => i.dcTag === tag).length} viz
              </Badge>
            ))
          )}
        </Group>
        <Group gap="sm" wrap="nowrap">
          <Tooltip label="Tool catalogue export is coming soon" disabled={mode === 'dashboard'}>
            <SegmentedControl
              size="xs"
              value={mode}
              onChange={(v) => v === 'dashboard' && setMode('dashboard')}
              data={[
                { label: 'Dashboard', value: 'dashboard' },
                { label: 'Tool catalogue (soon)', value: 'catalog', disabled: true },
              ]}
            />
          </Tooltip>
          <Button
            size="xs"
            leftSection={<Icon icon="mdi:export-variant" width={16} />}
            disabled={items.length === 0 || busy}
            loading={busy}
            onClick={doExport}
          >
            Export
          </Button>
        </Group>
      </Group>

      {items.length > 0 && (
        <Group gap={6} mt={6} wrap="wrap">
          {items.map((it) => (
            <Badge
              key={it.id}
              variant="outline"
              radius="sm"
              tt="none"
              rightSection={
                <ActionIcon size="xs" variant="transparent" color="gray" onClick={() => onRemove(it.id)}>
                  <Icon icon="mdi:close" width={12} />
                </ActionIcon>
              }
            >
              {it.dcTag}: {it.label}
            </Badge>
          ))}
        </Group>
      )}

      <Modal opened={!!result || !!error} onClose={() => { setResult(null); setError(null); }} title="Export result" size="xl">
        {error ? (
          <Text c="red">{error}</Text>
        ) : result ? (
          <Stack gap="md">
            <Group>
              <Button size="xs" variant="light" leftSection={<Icon icon="mdi:download" width={14} />} onClick={() => download('project.yaml', result.project_yaml)}>
                project.yaml
              </Button>
              <Button size="xs" variant="light" leftSection={<Icon icon="mdi:download" width={14} />} onClick={() => download('dashboard.yaml', result.dashboard_yaml)}>
                dashboard.yaml
              </Button>
            </Group>
            <Box>
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={4}>project.yaml</Text>
              <Code block fz="xs" style={{ maxHeight: 220, overflow: 'auto' }}>{result.project_yaml}</Code>
            </Box>
            <Box>
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={4}>dashboard.yaml</Text>
              <Code block fz="xs" style={{ maxHeight: 220, overflow: 'auto' }}>{result.dashboard_yaml}</Code>
            </Box>
          </Stack>
        ) : null}
      </Modal>
    </Box>
  );
};

export { dcTagForFile };
export default Cart;

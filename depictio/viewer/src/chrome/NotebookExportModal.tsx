import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  exportNotebook,
  fetchNotebookPreflight,
  type AnalysisState,
  type NotebookFormat,
  type NotebookInclusion,
  type NotebookPreflight,
} from 'depictio-react-core';

/**
 * Export the dashboard as a notebook: preflight first (what each tile becomes,
 * with a reason written for the reader), then the format, then the download.
 *
 * The server never executes anything: the marimo file is generated text and
 * the Jupyter / Quarto variants are derived from it with outputs excluded.
 */
interface NotebookExportModalProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  dashboardTitle?: string;
  getAnalysisState: () => AnalysisState;
}

const STATUS_META: Record<NotebookInclusion, { label: string; color: string }> = {
  code: { label: 'as code', color: 'teal' },
  api: { label: 'via Depictio', color: 'blue' },
  omitted: { label: 'omitted', color: 'gray' },
};

const FORMAT_HINT: Record<NotebookFormat, string> = {
  marimo: 'A reactive Python notebook: marimo edit <file>.py',
  ipynb: 'Open in JupyterLab: jupyter lab <file>.ipynb',
  quarto: 'Render a report: quarto render <file>.quarto.ipynb',
};

const NotebookExportModal: React.FC<NotebookExportModalProps> = ({
  opened,
  onClose,
  dashboardId,
  dashboardTitle,
  getAnalysisState,
}) => {
  const [state, setState] = useState<AnalysisState | null>(null);
  const [preflight, setPreflight] = useState<NotebookPreflight | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<NotebookFormat>('marimo');
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    const snapshot = getAnalysisState();
    setState(snapshot);
    setPreflight(null);
    setError(null);
    setDownloaded(null);
    const controller = new AbortController();
    fetchNotebookPreflight(dashboardId, snapshot, controller.signal)
      .then((res) => setPreflight(res))
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => controller.abort();
    // The snapshot is taken once per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, dashboardId]);

  const handleDownload = async () => {
    if (!state) return;
    setDownloading(true);
    setError(null);
    try {
      const filename = await exportNotebook(dashboardId, state, format);
      setDownloaded(filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  };

  const ipynbAvailable = preflight?.ipynb_available ?? true;
  const counts = preflight?.counts ?? {};

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={
        <Group gap="xs">
          <Icon icon="mdi:notebook-outline" width={20} />
          <Text fw={600}>Export as notebook</Text>
        </Group>
      }
    >
      <Stack gap="md" data-testid="notebook-export-modal">
        <Text size="sm" c="dimmed">
          {dashboardTitle ? `"${dashboardTitle}"` : 'This dashboard'}, every tab, with the
          filters, funnel order and groups you have right now — as a notebook you can keep
          working in. Each tile is reproduced as code where it can be, and rendered through
          Depictio otherwise.
        </Text>

        {error && (
          <Alert color="red" title="Export failed" data-testid="notebook-export-error">
            {error}
          </Alert>
        )}

        {!preflight && !error && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}

        {preflight && (
          <>
            <Group gap="xs" data-testid="notebook-export-counts">
              <Badge color="teal" variant="light">
                {counts.code ?? 0} as code
              </Badge>
              <Badge color="blue" variant="light">
                {counts.api ?? 0} via Depictio
              </Badge>
              {(counts.omitted ?? 0) > 0 && (
                <Badge color="gray" variant="light">
                  {counts.omitted} omitted
                </Badge>
              )}
              <Badge variant="outline">
                {counts.stages ?? 0} filter stage{(counts.stages ?? 0) === 1 ? '' : 's'}
              </Badge>
            </Group>
            <ScrollArea.Autosize mah={280}>
              <Table striped highlightOnHover withTableBorder fz="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Tile</Table.Th>
                    <Table.Th>Type</Table.Th>
                    <Table.Th>In the notebook</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {preflight.components.map((c) => {
                    const meta = STATUS_META[c.status];
                    return (
                      <Table.Tr key={c.index} data-testid={`notebook-export-row-${c.status}`}>
                        <Table.Td>
                          <Text size="xs" fw={500}>
                            {c.title || c.index}
                          </Text>
                          {c.section && (
                            <Text size="xs" c="dimmed">
                              {c.tab ? `${c.tab} · ` : ''}
                              {c.section}
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">
                            {c.component_type}
                            {c.kind ? ` · ${c.kind}` : ''}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Tooltip label={c.reason ?? ''} disabled={!c.reason} multiline w={320}>
                            <Group gap={6} wrap="nowrap">
                              <Badge size="xs" color={meta.color} variant="light">
                                {meta.label}
                              </Badge>
                              {c.name && (
                                <Text size="xs" c="dimmed" ff="monospace">
                                  {c.name}
                                </Text>
                              )}
                            </Group>
                          </Tooltip>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
            {preflight.warnings.length > 0 && (
              <Alert color="yellow" variant="light">
                <Stack gap={2}>
                  {preflight.warnings.map((w) => (
                    <Text size="xs" key={w}>
                      {w}
                    </Text>
                  ))}
                </Stack>
              </Alert>
            )}
          </>
        )}

        <Stack gap={4}>
          <Text fw={500} size="sm">
            Format
          </Text>
          <SegmentedControl
            value={format}
            onChange={(v) => setFormat(v as NotebookFormat)}
            data={[
              { label: 'marimo', value: 'marimo' },
              { label: 'Jupyter', value: 'ipynb', disabled: !ipynbAvailable },
              { label: 'Quarto', value: 'quarto', disabled: !ipynbAvailable },
            ]}
            data-testid="notebook-export-format"
          />
          <Text size="xs" c="dimmed">
            {FORMAT_HINT[format]}
            {!ipynbAvailable && ' — Jupyter and Quarto variants need marimo on the server.'}
          </Text>
        </Stack>

        {downloaded && (
          <Alert color="teal" variant="light" data-testid="notebook-export-done">
            Downloaded <code>{downloaded}</code>. Set <code>DEPICTIO_API_URL</code> and{' '}
            <code>DEPICTIO_API_TOKEN</code> (a long-lived token from the CLI agents page) before
            running it.
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Close
          </Button>
          <Button
            leftSection={<Icon icon="mdi:download" width={16} />}
            onClick={handleDownload}
            loading={downloading}
            disabled={!state || !preflight}
            data-testid="notebook-export-download"
          >
            Download
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default NotebookExportModal;

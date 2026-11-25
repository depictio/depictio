import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  listDashboards,
  preflightStaticExport,
  type StaticExportPreflight,
} from 'depictio-react-core';
import { formatBundleBytes } from './format';
import CollectionInventory from '../export/CollectionInventory';

interface DashboardPreview {
  id: string;
  title: string;
  preflight: StaticExportPreflight | null;
  error: string | null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** The binding preflight of one dashboard, retried while the server's two
 *  preflight slots are taken (429). */
async function preflightWithRetry(dashboardId: string): Promise<StaticExportPreflight> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await preflightStaticExport(dashboardId, 'off');
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status !== 429 || attempt >= 5) throw err;
      await sleep(5000);
    }
  }
}

const TierCounts: React.FC<{ counts: StaticExportPreflight['counts'] }> = ({ counts }) => (
  <Group gap={6}>
    {(['live', 'partial', 'frozen', 'omitted'] as const)
      .filter((k) => counts[k] > 0)
      .map((k) => (
        <Badge key={k} variant="light" color="gray" size="sm">
          {counts[k]} {k}
        </Badge>
      ))}
  </Group>
);

const DashboardInventory: React.FC<{ preview: DashboardPreview }> = ({ preview }) => {
  const { preflight } = preview;
  return (
    <Paper withBorder radius="md" p="sm" data-testid="public-download-preview-dashboard">
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Text fw={600} size="sm" truncate>
            {preview.title}
          </Text>
          {preflight?.size_estimate && (
            <Text size="xs" c="dimmed">
              about {formatBundleBytes(preflight.size_estimate.estimated_total_bytes)}
            </Text>
          )}
        </Group>
        {preview.error && (
          <Text size="xs" c="red">
            {preview.error}
          </Text>
        )}
        {!preflight && !preview.error && <Loader size="xs" />}
        {preflight && (
          <>
            <TierCounts counts={preflight.counts} />
            <CollectionInventory collections={preflight.collections ?? []} />
          </>
        )}
      </Stack>
    </Paper>
  );
};

/**
 * What visitors of a public project will be able to download, before the
 * owner lets them (#1480): per dashboard, the collections the offline copy
 * carries, their columns and row counts, which tables ship whole, the size and
 * which tiles stay interactive. Read from the same binding preflight a build
 * runs (Python runtime off, as the public copy is built), so the list is the
 * file's content, not a guess. Turning the download on needs the box ticked.
 */
const PublicDownloadPreviewModal: React.FC<{
  opened: boolean;
  projectId: string;
  projectName?: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}> = ({ opened, projectId, projectName, busy, onClose, onConfirm }) => {
  const [previews, setPreviews] = useState<DashboardPreview[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState(false);

  useEffect(() => {
    if (!opened) return;
    let alive = true;
    setPreviews(null);
    setListError(null);
    setReviewed(false);
    (async () => {
      try {
        const all = await listDashboards(false);
        const mine = all
          .filter((d) => String(d.project_id ?? '') === projectId && d.is_main_tab !== false)
          .map((d) => ({
            id: String(d.dashboard_id),
            title: d.title || 'Untitled dashboard',
            preflight: null,
            error: null,
          }));
        if (!alive) return;
        setPreviews(mine);
        // One at a time: the server runs at most two data-reading previews.
        for (const item of mine) {
          let next: DashboardPreview;
          try {
            next = { ...item, preflight: await preflightWithRetry(item.id) };
          } catch (err) {
            next = { ...item, error: (err as Error).message || 'Preview failed' };
          }
          if (!alive) return;
          setPreviews((prev) => (prev ?? []).map((p) => (p.id === item.id ? next : p)));
        }
      } catch (err) {
        if (alive) setListError((err as Error).message || 'Could not list the dashboards');
      }
    })();
    return () => {
      alive = false;
    };
  }, [opened, projectId]);

  const done = previews !== null && previews.every((p) => p.preflight || p.error);
  const failed = previews?.some((p) => p.error) ?? false;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={<Text fw={600}>Let visitors download an offline copy</Text>}
      data-testid="public-download-preview-modal"
    >
      <Stack gap="md">
        <Text size="sm">
          Anyone who can open {projectName ? <b>{projectName}</b> : 'this project'} will be
          able to download each dashboard below as one HTML file that works offline. The file
          carries the data listed here; once downloaded, no access control follows it.
        </Text>
        <Alert variant="light" icon={<Icon icon="mdi:shield-check-outline" width={18} />}>
          The copy is built at each dashboard's default view and names no one: no email, no
          Python runtime, and code-mode figures ship as pictures without their code. It is
          rebuilt after a save or an ingestion.
        </Alert>
        {listError && (
          <Alert color="red" variant="light">
            {listError}
          </Alert>
        )}
        {previews === null && !listError && <Loader size="sm" />}
        {previews !== null && previews.length === 0 && (
          <Text size="sm" c="dimmed">
            This project has no dashboard yet: nothing would be offered until one is created.
          </Text>
        )}
        {previews !== null && previews.length > 0 && (
          <ScrollArea.Autosize mah="50vh" type="auto">
            <Stack gap="sm">
              {previews.map((p) => (
                <DashboardInventory key={p.id} preview={p} />
              ))}
            </Stack>
          </ScrollArea.Autosize>
        )}
        <Checkbox
          checked={reviewed}
          onChange={(e) => setReviewed(e.currentTarget.checked)}
          disabled={!done || failed}
          label="I have reviewed what visitors will be able to download"
          data-testid="public-download-reviewed"
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={!reviewed || !done || failed}
            loading={busy}
            data-testid="public-download-confirm"
          >
            Turn on
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default PublicDownloadPreviewModal;

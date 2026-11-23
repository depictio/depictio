/*
 * ReportEditorApp: the page at /dashboard-report/{dashboardId}.
 *
 * A notebook export turns a dashboard into a Quarto report. The report layer
 * stored on the dashboard is what the author writes around the tiles: a cover,
 * an introduction and a conclusion, and per tile whether it is in the report
 * and the PDF, its caption, order and section.
 *
 * Two halves side by side. On the left the author edits (cover, introduction,
 * the structure mirrored from the dashboard, conclusion); on the right the real
 * report is shown in a frame and every edit is applied to it at once, by
 * postMessage (PREVIEW_CONTRACT.md). Quarto only runs again when the filter
 * state changes.
 *
 * Only owners and editors of the project reach it (the API answers 404 to
 * anyone else, and while the feature is off).
 */
import React, { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  AppShell,
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { usePageTitle } from '../branding';
import { useReportEditorEnabled } from '../hooks/useReportEditorEnabled';
import { useServerInfo } from '../hooks/useServerInfo';
import CollapsiblePanel from './CollapsiblePanel';
import CoverForm from './CoverForm';
import PreviewPane from './PreviewPane';
import RichDocField from './RichDocField';
import { SnapshotContext } from './SnapshotContext';
import StructurePanel from './StructurePanel';
import { buildTabViews, docSummary } from './model';
import { buildPatch, tileKey } from './previewProtocol';
import { useExactPdf } from './useExactPdf';
import { useFrameBridge } from './useFrameBridge';
import { usePreviewJob } from './usePreviewJob';
import { useReportLayer } from './useReportLayer';
import type { ReportSaveStatus } from './useReportLayer';

const HEADER_HEIGHT = 56;

/** The dashboard id out of `/dashboard-report/{id}`. */
function dashboardIdFromPath(): string {
  const match = window.location.pathname.match(/^\/dashboard-report\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

function statusLabel(status: ReportSaveStatus, error: string | null): { text: string; color: string } {
  switch (status) {
    case 'saving':
      return { text: 'Saving…', color: 'gray' };
    case 'saved':
      return { text: 'Saved', color: 'green' };
    case 'error':
      return { text: error ? `Not saved: ${error}` : 'Not saved', color: 'red' };
    case 'conflict':
      return { text: 'Changed by someone else', color: 'red' };
    default:
      return { text: 'Up to date', color: 'gray' };
  }
}

interface Selection {
  tabId: string;
  componentId: string;
}

const ReportEditorApp: React.FC = () => {
  const dashboardId = useMemo(dashboardIdFromPath, []);
  const enabled = useReportEditorEnabled();
  const { loading: serverInfoLoading } = useServerInfo();
  const api = useReportLayer(dashboardId);
  const { layer, outline } = api;
  const [selected, setSelected] = useState<Selection | null>(null);
  const [revealToken, setRevealToken] = useState(0);
  const [fold, setFold] = useState({ open: true, n: 0 });

  usePageTitle(outline?.title ? `Report: ${outline.title}` : 'Report');

  const tabs = useMemo(
    () => (layer && outline ? buildTabViews(outline.tabs, layer) : []),
    [layer, outline],
  );
  const patch = useMemo(
    () => (layer && outline ? buildPatch(layer, outline, selected && {
      tab_id: selected.tabId,
      component_id: selected.componentId,
    }) : null),
    [layer, outline, selected],
  );

  const ready = Boolean(enabled && layer && outline && !api.loadError);
  const stateKey = useMemo(() => JSON.stringify(layer?.state ?? null), [layer?.state]);
  const job = usePreviewJob(dashboardId, ready, stateKey, api.flush);

  const onFrameSelect = useCallback((tabId: string, componentId: string) => {
    setSelected({ tabId, componentId });
    setRevealToken((t) => t + 1);
  }, []);
  const bridge = useFrameBridge(job.previewUrl, patch, onFrameSelect);
  const snapshotSource = useMemo(
    () => ({ snapshots: bridge.snapshots, styles: bridge.styles, baseUrl: job.previewUrl }),
    [bridge.snapshots, bridge.styles, job.previewUrl],
  );
  const pdf = useExactPdf(dashboardId, layer, api.flush);

  const onSelect = useCallback((tabId: string, componentId: string | null) => {
    setSelected(componentId ? { tabId, componentId } : null);
  }, []);

  const editorUrl = `/dashboard-edit/${dashboardId}`;
  const status = statusLabel(api.saveStatus, api.saveError);
  const conflict = api.saveStatus === 'conflict';

  const header = (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Button
          component="a"
          href={editorUrl}
          variant="subtle"
          color="gray"
          size="xs"
          leftSection={<Icon icon="mdi:arrow-left" width={16} />}
          data-testid="report-back-to-editor"
        >
          Back to editor
        </Button>
        <Icon icon="mdi:file-document-edit-outline" width={24} />
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Title order={4} lineClamp={1}>
            {outline?.title ?? 'Report'}
          </Title>
          <Text size="xs" c="dimmed">
            Report editor
          </Text>
        </Stack>
      </Group>
      <Group gap="sm" wrap="nowrap">
        {pdf.error && (
          <Text size="xs" c="red" maw={280} lineClamp={2} data-testid="report-pdf-error">
            {pdf.error}
          </Text>
        )}
        <Badge
          color={status.color}
          variant="light"
          size="lg"
          tt="none"
          data-testid="report-save-status"
        >
          {status.text}
        </Badge>
        {conflict && (
          <Button
            size="xs"
            variant="light"
            color="red"
            leftSection={<Icon icon="mdi:reload" width={14} />}
            onClick={api.reload}
            data-testid="report-reload"
          >
            Reload
          </Button>
        )}
        <Button
          size="xs"
          variant="default"
          leftSection={<Icon icon="mdi:file-pdf-box" width={16} />}
          loading={pdf.busy}
          disabled={!layer || conflict}
          onClick={pdf.run}
          data-testid="report-exact-pdf"
        >
          Exact PDF
        </Button>
      </Group>
    </Group>
  );

  const centered = (content: React.ReactNode) => (
    <Center mih={300} h={`calc(100dvh - ${HEADER_HEIGHT}px)`}>
      {content}
    </Center>
  );

  const body = (() => {
    if (!dashboardId) {
      return <Alert color="red" m="md">This address names no dashboard.</Alert>;
    }
    if (serverInfoLoading && !enabled) return centered(<Loader />);
    if (!enabled) {
      return centered(
        <Stack align="center" gap="sm" maw={420} ta="center">
          <Icon icon="mdi:file-document-remove-outline" width={48} />
          <Title order={3}>The report editor is not available</Title>
          <Text c="dimmed">This server does not offer it.</Text>
          <Button component="a" href={editorUrl} variant="light">
            Back to editor
          </Button>
        </Stack>,
      );
    }
    if (api.loading && !layer) return centered(<Loader />);
    if (api.loadError || !layer || !outline) {
      return centered(
        <Stack align="center" gap="sm" maw={460} ta="center">
          <Icon icon="mdi:alert-circle-outline" width={48} />
          <Title order={3}>The report could not be opened</Title>
          <Text c="dimmed">
            {api.loadError ??
              "Only the owners and editors of the dashboard's project can edit its report."}
          </Text>
          <Group>
            <Button component="a" href={editorUrl} variant="default">
              Back to editor
            </Button>
            <Button variant="light" onClick={api.reload}>
              Try again
            </Button>
          </Group>
        </Stack>,
      );
    }

    return (
      <SnapshotContext.Provider value={snapshotSource}>
      <Box
        data-testid="report-editor"
        style={{ display: 'flex', height: `calc(100dvh - ${HEADER_HEIGHT}px)` }}
      >
        <Box
          p="md"
          style={{ flex: '1 1 50%', minWidth: 0, overflowY: 'auto' }}
          data-testid="report-edit-column"
        >
          <Stack gap="md">
            {conflict && (
              <Alert
                color="red"
                variant="light"
                title={
                  api.conflict?.updated_by
                    ? `Modified by ${api.conflict.updated_by}`
                    : 'Modified by someone else'
                }
                data-testid="report-conflict"
              >
                <Group justify="space-between" wrap="nowrap">
                  <Text size="sm">
                    {api.conflict?.message ?? 'The report changed since you opened it.'} Your last
                    edits were not saved. Reload to continue from the stored version.
                  </Text>
                  <Button size="xs" color="red" onClick={api.reload}>
                    Reload
                  </Button>
                </Group>
              </Alert>
            )}

            <CoverForm layer={layer} defaults={outline.cover_defaults} onEdit={api.edit} />

            <CollapsiblePanel
              icon="mdi:text-box-outline"
              title="Introduction"
              summary={docSummary(layer.intro)}
              testId="report-intro-panel"
            >
              <Stack gap="xs">
                {layer.seeded_from_notes && (
                  <Badge
                    variant="light"
                    color="blue"
                    w="fit-content"
                    data-testid="report-seeded-note"
                  >
                    Drafted from the dashboard notes
                  </Badge>
                )}
                <RichDocField
                  key={`intro-${api.epoch}`}
                  description="Opens the report, before the first tab."
                  value={layer.intro}
                  testId="report-intro"
                  onChange={(doc) =>
                    api.edit((l) => ({ ...l, intro: doc, seeded_from_notes: false }))
                  }
                />
              </Stack>
            </CollapsiblePanel>

            <Box>
              <Group justify="space-between" align="flex-end" wrap="nowrap" mb="xs">
                <Box>
                  <Text fw={600}>Structure</Text>
                  <Text size="xs" c="dimmed">
                    Tick what goes in the report, drag to reorder, click a card to set its caption
                    and PDF options.
                  </Text>
                </Box>
                <Group gap={4} wrap="nowrap" style={{ flex: 'none' }}>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="gray"
                    onClick={() => setFold((f) => ({ open: true, n: f.n + 1 }))}
                    data-testid="report-expand-all"
                  >
                    Expand all
                  </Button>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="gray"
                    onClick={() => setFold((f) => ({ open: false, n: f.n + 1 }))}
                    data-testid="report-collapse-all"
                  >
                    Collapse all
                  </Button>
                </Group>
              </Group>
              <StructurePanel
                tabs={tabs}
                outline={outline}
                selectedKey={selected ? tileKey(selected.tabId, selected.componentId) : null}
                revealToken={revealToken}
                thumbs={bridge.thumbs}
                fold={fold}
                onEdit={api.edit}
                onSelect={onSelect}
              />
            </Box>

            <CollapsiblePanel
              icon="mdi:text-box-check-outline"
              title="Conclusion"
              summary={docSummary(layer.conclusion)}
              testId="report-conclusion-panel"
            >
              <RichDocField
                key={`conclusion-${api.epoch}`}
                description="Closes the report, after the last tab."
                value={layer.conclusion}
                testId="report-conclusion"
                onChange={(doc) => api.edit((l) => ({ ...l, conclusion: doc }))}
              />
            </CollapsiblePanel>
          </Stack>
        </Box>
        <Box
          p="md"
          style={{
            flex: '1 1 50%',
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            borderLeft: '1px solid var(--mantine-color-default-border)',
          }}
        >
          <PreviewPane job={job} bridge={bridge} />
        </Box>
      </Box>
      </SnapshotContext.Provider>
    );
  })();

  return (
    <AppShell header={{ height: HEADER_HEIGHT }} padding={0} data-testid="app-shell">
      <AppShell.Header>{header}</AppShell.Header>
      <AppShell.Main>{body}</AppShell.Main>
    </AppShell>
  );
};

export default ReportEditorApp;

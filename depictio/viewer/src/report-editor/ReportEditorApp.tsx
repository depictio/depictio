/*
 * ReportEditorApp: the page at /dashboard-report/{dashboardId}.
 *
 * A notebook export turns a dashboard into a Quarto report. The report layer
 * stored on the dashboard is what the author writes around the tiles: a cover,
 * an introduction and a conclusion, and per tile whether it is in the report
 * and the PDF, its caption, order and section. This page edits that layer next
 * to the report's structure (the outline), and "Exact preview" renders the
 * real report.
 *
 * Only owners and editors of the project reach it (the API answers 404 to
 * anyone else, and while the feature is off).
 */
import React, { useMemo, useState } from 'react';
import {
  Alert,
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { usePageTitle } from '../branding';
import { useReportEditorEnabled } from '../hooks/useReportEditorEnabled';
import { useServerInfo } from '../hooks/useServerInfo';
import CoverForm from './CoverForm';
import OutlineTab from './OutlineTab';
import PreviewDrawer from './PreviewDrawer';
import RichDocField from './RichDocField';
import { buildTabViews, moveTab, stateFilters } from './model';
import { useReportLayer } from './useReportLayer';
import type { ReportSaveStatus } from './useReportLayer';

/** The dashboard id out of `/dashboard-report/{id}`. */
function dashboardIdFromPath(): string {
  const match = window.location.pathname.match(/^\/dashboard-report\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

function statusLabel(status: ReportSaveStatus, error: string | null): { text: string; color?: string } {
  switch (status) {
    case 'saving':
      return { text: 'Saving…', color: 'dimmed' };
    case 'saved':
      return { text: 'Saved', color: 'dimmed' };
    case 'error':
      return { text: error ? `Not saved: ${error}` : 'Not saved', color: 'red' };
    case 'conflict':
      return { text: 'Changed by someone else', color: 'red' };
    default:
      return { text: '', color: 'dimmed' };
  }
}

const ReportEditorApp: React.FC = () => {
  const dashboardId = useMemo(dashboardIdFromPath, []);
  const enabled = useReportEditorEnabled();
  const { loading: serverInfoLoading } = useServerInfo();
  const api = useReportLayer(dashboardId);
  const { layer, outline } = api;
  const [previewOpen, setPreviewOpen] = useState(false);

  usePageTitle(outline?.title ? `Report: ${outline.title}` : 'Report');

  const tabs = useMemo(
    () => (layer && outline ? buildTabViews(outline.tabs, layer) : []),
    [layer, outline],
  );
  const filters = useMemo(() => stateFilters(layer?.state ?? null), [layer?.state]);

  const editorUrl = `/dashboard-edit/${dashboardId}`;
  const previewAvailable = outline?.preview_available ?? false;
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
        <Text size="sm" c={status.color} data-testid="report-save-status">
          {status.text}
        </Text>
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
        <Tooltip
          label={outline?.preview_unavailable_reason ?? 'The preview is not available here.'}
          disabled={previewAvailable || !outline}
          multiline
          w={320}
        >
          {/* A disabled button swallows hover: the span carries the tooltip. */}
          <span>
            <Button
              size="xs"
              leftSection={<Icon icon="mdi:file-eye-outline" width={16} />}
              disabled={!previewAvailable || conflict}
              onClick={() => setPreviewOpen(true)}
              data-testid="report-preview-button"
            >
              Exact preview
            </Button>
          </span>
        </Tooltip>
      </Group>
    </Group>
  );

  const body = (() => {
    if (!dashboardId) {
      return <Alert color="red">This address names no dashboard.</Alert>;
    }
    if (serverInfoLoading && !enabled) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (!enabled) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="sm" maw={420} ta="center">
            <Icon icon="mdi:file-document-remove-outline" width={48} />
            <Title order={3}>The report editor is not available</Title>
            <Text c="dimmed">This server does not offer it.</Text>
            <Button component="a" href={editorUrl} variant="light">
              Back to editor
            </Button>
          </Stack>
        </Center>
      );
    }
    if (api.loading && !layer) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (api.loadError || !layer || !outline) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="sm" maw={460} ta="center">
            <Icon icon="mdi:alert-circle-outline" width={48} />
            <Title order={3}>The report could not be opened</Title>
            <Text c="dimmed">
              {api.loadError ??
                'Only the owners and editors of the dashboard\'s project can edit its report.'}
            </Text>
            <Group>
              <Button component="a" href={editorUrl} variant="default">
                Back to editor
              </Button>
              <Button variant="light" onClick={api.reload}>
                Try again
              </Button>
            </Group>
          </Stack>
        </Center>
      );
    }

    const notesDraft = layer.seeded_from_notes;
    return (
      <Stack gap="md" data-testid="report-editor">
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
                {api.conflict?.message ??
                  'The report changed since you opened it.'}{' '}
                Your last edits were not saved. Reload to continue from the stored version.
              </Text>
              <Button size="xs" color="red" onClick={api.reload}>
                Reload
              </Button>
            </Group>
          </Alert>
        )}

        <CoverForm layer={layer} defaults={outline.cover_defaults} onEdit={api.edit} />

        <Card withBorder radius="md" p="md">
          <Stack gap="xs">
            {notesDraft && (
              <Badge variant="light" color="blue" w="fit-content" data-testid="report-seeded-note">
                Drafted from the dashboard notes
              </Badge>
            )}
            <RichDocField
              key={`intro-${api.epoch}`}
              label="Introduction"
              description="Opens the report, before the first tab."
              value={layer.intro}
              testId="report-intro"
              onChange={(doc) =>
                api.edit((l) => ({ ...l, intro: doc, seeded_from_notes: false }))
              }
            />
          </Stack>
        </Card>

        <Box>
          <Text fw={600} mb="xs">
            Structure
          </Text>
          <Stack gap="md">
            {tabs.map((tab, i) => (
              <OutlineTab
                key={tab.tabId}
                tab={tab}
                index={i}
                count={tabs.length}
                filters={filters}
                onEdit={api.edit}
                onMoveTab={(dir) => api.edit((l) => moveTab(l, tabs, i, i + dir))}
              />
            ))}
          </Stack>
        </Box>

        <Card withBorder radius="md" p="md">
          <RichDocField
            key={`conclusion-${api.epoch}`}
            label="Conclusion"
            description="Closes the report, after the last tab."
            value={layer.conclusion}
            testId="report-conclusion"
            onChange={(doc) => api.edit((l) => ({ ...l, conclusion: doc }))}
          />
        </Card>
      </Stack>
    );
  })();

  return (
    <AppShell header={{ height: 56 }} padding="md" data-testid="app-shell">
      <AppShell.Header>{header}</AppShell.Header>
      <AppShell.Main>
        <Container size="lg" p="md">
          {body}
        </Container>
      </AppShell.Main>
      <PreviewDrawer
        opened={previewOpen}
        onClose={() => setPreviewOpen(false)}
        dashboardId={dashboardId}
        beforeRun={api.flush}
      />
    </AppShell>
  );
};

export default ReportEditorApp;

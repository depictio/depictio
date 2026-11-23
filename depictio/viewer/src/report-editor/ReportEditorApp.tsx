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
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core';
import {
  ArrowLeft,
  BookOpen,
  ChevronsDownUp,
  ChevronsUpDown,
  CircleAlert,
  CloudCheck,
  FileDown,
  FileText,
  FileX,
  Flag,
  ListTree,
  Moon,
  RefreshCw,
  ScrollText,
  Signature,
  Sun,
  TriangleAlert,
} from 'lucide-react';

import { usePageTitle } from '../branding';
import { STROKE } from '../chrome/variants/glass/icons';
import { useChromeVariant } from '../chrome/variants';
import { useColorScheme } from '../hooks/useColorScheme';
import { useReportEditorEnabled } from '../hooks/useReportEditorEnabled';
import { useServerInfo } from '../hooks/useServerInfo';
import CollapsiblePanel from './CollapsiblePanel';
import CoverForm from './CoverForm';
import EditorSection from './EditorSection';
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
import './report-editor.css';

/** The dashboard id out of `/dashboard-report/{id}`. */
function dashboardIdFromPath(): string {
  const match = window.location.pathname.match(/^\/dashboard-report\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

interface StatusView {
  text: string;
  color: string;
  icon: React.ReactNode;
}

function statusLabel(status: ReportSaveStatus, error: string | null): StatusView {
  switch (status) {
    case 'saving':
      return { text: 'Saving…', color: 'gray', icon: <Loader size={11} color="gray" /> };
    case 'saved':
      return {
        text: 'Saved',
        color: 'green',
        icon: <CloudCheck size={13} strokeWidth={STROKE} aria-hidden />,
      };
    case 'error':
      return {
        text: error ? `Not saved: ${error}` : 'Not saved',
        color: 'red',
        icon: <TriangleAlert size={13} strokeWidth={STROKE} aria-hidden />,
      };
    case 'conflict':
      return {
        text: 'Changed by someone else',
        color: 'red',
        icon: <TriangleAlert size={13} strokeWidth={STROKE} aria-hidden />,
      };
    default:
      return {
        text: 'Up to date',
        color: 'gray',
        icon: <CloudCheck size={13} strokeWidth={STROKE} aria-hidden />,
      };
  }
}

interface Selection {
  tabId: string;
  componentId: string;
}

const ReportEditorApp: React.FC = () => {
  // The chrome style (Paper by default) the page's tokens come from.
  useChromeVariant();
  const dashboardId = useMemo(dashboardIdFromPath, []);
  const enabled = useReportEditorEnabled();
  const { loading: serverInfoLoading } = useServerInfo();
  const api = useReportLayer(dashboardId);
  const { layer, outline } = api;
  const [selected, setSelected] = useState<Selection | null>(null);
  const [revealToken, setRevealToken] = useState(0);
  const [fold, setFold] = useState({ open: true, n: 0 });
  // The app's own scheme: the preview frame follows it, not the browser's.
  const scheme = useComputedColorScheme('light', { getInitialValueInEffect: false });
  const { toggle: toggleScheme } = useColorScheme();

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
  const bridge = useFrameBridge(job.previewUrl, patch, onFrameSelect, scheme);
  const snapshotSource = useMemo(
    () => ({
      snapshots: bridge.snapshots,
      styles: bridge.styles,
      baseUrl: job.previewUrl,
      state: layer?.state ?? null,
    }),
    [bridge.snapshots, bridge.styles, job.previewUrl, layer?.state],
  );
  const pdf = useExactPdf(dashboardId, layer, api.flush);

  const onSelect = useCallback((tabId: string, componentId: string | null) => {
    setSelected(componentId ? { tabId, componentId } : null);
  }, []);

  const editorUrl = `/dashboard-edit/${dashboardId}`;
  const status = statusLabel(api.saveStatus, api.saveError);
  const conflict = api.saveStatus === 'conflict';
  const dark = scheme === 'dark';

  const header = (
    <header className="re-top" data-testid="report-header">
      <Button
        component="a"
        href={editorUrl}
        variant="subtle"
        color="gray"
        size="sm"
        leftSection={<ArrowLeft size={17} strokeWidth={STROKE} />}
        data-testid="report-back-to-editor"
      >
        Back to editor
      </Button>
      <span className="re-top-rule" aria-hidden />
      <div className="re-top-title">
        <span className="re-chip" aria-hidden>
          <FileText size={18} strokeWidth={STROKE} />
        </span>
        <div className="re-top-text">
          <span className="re-top-name">Report editor</span>
          <span className="re-top-sub" title={outline?.title ?? undefined}>
            {outline?.title ?? 'Loading the dashboard…'}
          </span>
        </div>
      </div>
      <span className="re-top-grow" />
      <div className="re-top-actions">
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
          leftSection={status.icon}
          data-testid="report-save-status"
        >
          {status.text}
        </Badge>
        {conflict && (
          <Button
            size="xs"
            variant="light"
            color="red"
            leftSection={<RefreshCw size={14} strokeWidth={STROKE} />}
            onClick={api.reload}
            data-testid="report-reload"
          >
            Reload
          </Button>
        )}
        <Button
          size="sm"
          variant="default"
          leftSection={<FileDown size={17} strokeWidth={STROKE} />}
          loading={pdf.busy}
          disabled={!layer || conflict}
          onClick={pdf.run}
          data-testid="report-exact-pdf"
        >
          Exact PDF
        </Button>
        <Tooltip label={dark ? 'Switch to light theme' : 'Switch to dark theme'} withArrow>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="lg"
            onClick={toggleScheme}
            aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
            data-testid="report-theme-toggle"
          >
            {dark ? (
              <Sun size={19} strokeWidth={STROKE} />
            ) : (
              <Moon size={19} strokeWidth={STROKE} />
            )}
          </ActionIcon>
        </Tooltip>
      </div>
    </header>
  );

  const centered = (content: React.ReactNode) => (
    <Center mih={300} style={{ flex: 1, minHeight: 0 }}>
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
          <FileX size={44} strokeWidth={STROKE} aria-hidden />
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
          <CircleAlert size={44} strokeWidth={STROKE} aria-hidden />
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
        <div className="re-body" data-testid="report-editor">
          <div className="re-edit" data-testid="report-edit-column">
            <div className="re-edit-inner">
              {conflict && (
                <Alert
                  color="red"
                  variant="light"
                  radius="lg"
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

              <EditorSection
                icon={BookOpen}
                title="Front matter"
                description="What opens the report: the cover, then an introduction before the first tab."
              >
                <CoverForm layer={layer} defaults={outline.cover_defaults} onEdit={api.edit} />

                <CollapsiblePanel
                  icon={ScrollText}
                  title="Introduction"
                  summary={docSummary(layer.intro)}
                  testId="report-intro-panel"
                >
                  <Stack gap="xs" pt="xs">
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
              </EditorSection>

              <EditorSection
                icon={ListTree}
                title="Structure"
                description="Tick what goes in the report, drag to reorder, click a card to set its caption and PDF options."
                actions={
                  <Group gap={2} wrap="nowrap" style={{ flex: 'none' }}>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="gray"
                      leftSection={<ChevronsUpDown size={14} strokeWidth={STROKE} />}
                      onClick={() => setFold((f) => ({ open: true, n: f.n + 1 }))}
                      data-testid="report-expand-all"
                    >
                      Expand all
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="gray"
                      leftSection={<ChevronsDownUp size={14} strokeWidth={STROKE} />}
                      onClick={() => setFold((f) => ({ open: false, n: f.n + 1 }))}
                      data-testid="report-collapse-all"
                    >
                      Collapse all
                    </Button>
                  </Group>
                }
              >
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
              </EditorSection>

              <EditorSection
                icon={Flag}
                title="Closing"
                description="How the report ends: a conclusion after the last tab."
              >
                <CollapsiblePanel
                  icon={Signature}
                  title="Conclusion"
                  summary={docSummary(layer.conclusion)}
                  testId="report-conclusion-panel"
                >
                  <Box pt="xs">
                    <RichDocField
                      key={`conclusion-${api.epoch}`}
                      description="Closes the report, after the last tab."
                      value={layer.conclusion}
                      testId="report-conclusion"
                      onChange={(doc) => api.edit((l) => ({ ...l, conclusion: doc }))}
                    />
                  </Box>
                </CollapsiblePanel>
              </EditorSection>
            </div>
          </div>
          <div className="re-preview">
            <PreviewPane job={job} bridge={bridge} scheme={scheme} />
          </div>
        </div>
      </SnapshotContext.Provider>
    );
  })();

  return (
    <div className="re-root" data-testid="app-shell">
      {header}
      {body}
    </div>
  );
};

export default ReportEditorApp;

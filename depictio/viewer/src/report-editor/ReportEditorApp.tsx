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
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Group,
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
  Check,
  CircleAlert,
  CircleCheck,
  FileDown,
  FileText,
  FileX,
  Flag,
  ListTree,
  PanelLeftClose,
  PanelLeftOpen,
  Moon,
  RefreshCw,
  ScrollText,
  Settings2,
  Signature,
  Sun,
  TriangleAlert,
} from 'lucide-react';

import { fetchAllDashboards } from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';
import DepictioRose from '../components/rose/DepictioRose';
import { usePageTitle } from '../branding';
import { STROKE } from '../chrome/variants/glass/icons';
import { useChromeVariant } from '../chrome/variants';
import TabLinkProvider from '../chrome/TabLinkProvider';
import { useColorScheme } from '../hooks/useColorScheme';
import { useReportEditorEnabled } from '../hooks/useReportEditorEnabled';
import { useServerInfo } from '../hooks/useServerInfo';
import CollapsiblePanel from './CollapsiblePanel';
import CoverForm from './CoverForm';
import EditorSection from './EditorSection';
import PreviewPane from './PreviewPane';
import ReportSettingsModal, { settingsOf } from './ReportSettingsModal';
import RichDocField from './RichDocField';
import { SnapshotContext } from './SnapshotContext';
import StructurePanel from './StructurePanel';
import { buildTabViews, docSummary } from './model';
import { buildPatch, tileKey } from './previewProtocol';
import { useExactPdf } from './useExactPdf';
import { useFrameBridge } from './useFrameBridge';
import { useScrollSync } from './useScrollSync';
import { useSplitPane } from './useSplitPane';
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
      return { text: 'Saving…', color: 'gray', icon: <DepictioRose mode="loading" size={12} label="" /> };
    case 'saved':
      return {
        text: 'Saved',
        color: 'green',
        icon: <CircleCheck size={14} strokeWidth={STROKE} aria-hidden />,
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
        icon: <Check size={14} strokeWidth={STROKE} aria-hidden />,
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
  // The report alone: the editing column folds away and the preview takes
  // the page, to read the report as its readers will.
  const [reportOnly, setReportOnly] = useState(false);
  // The tab family, so a text tile's `[…](tab:Name)` links wear the tab's
  // icon and colour as on the dashboard (a stepper's tab, the "how to read"
  // tiles), instead of falling back to plain text.
  const [family, setFamily] = useState<DashboardSummary[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchAllDashboards()
      .then((all) => {
        if (cancelled) return;
        const main = all.find((d) => d.dashboard_id === dashboardId);
        const parentId = main?.parent_dashboard_id || dashboardId;
        setFamily(
          all
            .filter((d) => d.dashboard_id === parentId || d.parent_dashboard_id === parentId)
            .sort((a, b) => (a.tab_order ?? 0) - (b.tab_order ?? 0)),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);
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

  // A server that cannot render (no Quarto, renders off) says so in the
  // outline: no job is started, the pane explains and Exact PDF is off.
  const unavailable = outline && outline.preview_available === false
    ? outline.preview_unavailable_reason || 'Reports cannot be rendered on this deployment.'
    : null;
  const ready = Boolean(enabled && layer && outline && !api.loadError && !unavailable);
  // The preview renders again when the state changes, and when the report's
  // settings do: those change the document, not one tile the frame can patch.
  const stateKey = useMemo(
    () => JSON.stringify({ state: layer?.state ?? null, settings: layer ? settingsOf(layer) : null }),
    [layer],
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const job = usePreviewJob(dashboardId, ready, stateKey, api.flush);

  // Scroll sync: the bridge hands the frame's "visible" tile to the column
  // (through a ref: the hook that scrolls it needs the bridge's sender).
  const [syncScroll, setSyncScroll] = useState(true);
  const syncScrollRef = useRef(syncScroll);
  syncScrollRef.current = syncScroll;
  const editColumnRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const split = useSplitPane(bodyRef);
  const followFrameRef = useRef<((tabId: string, componentId: string) => void) | null>(null);
  const onFrameSelect = useCallback((tabId: string, componentId: string) => {
    setSelected({ tabId, componentId });
    // With scroll sync on, the column goes to the card through the sync's own
    // guard: a plain reveal scrolled the column unannounced, the sync took it
    // for the author's scroll and sent the preview to the card then at the
    // column's top, away from the tile just clicked.
    if (syncScrollRef.current && followFrameRef.current) followFrameRef.current(tabId, componentId);
    else setRevealToken((t) => t + 1);
  }, []);
  const onFrameVisible = useCallback(
    (tabId: string, componentId: string) => followFrameRef.current?.(tabId, componentId),
    [],
  );
  const bridge = useFrameBridge(job.previewUrl, patch, onFrameSelect, scheme, onFrameVisible);
  followFrameRef.current = useScrollSync(editColumnRef, syncScroll, bridge.frameReady, bridge.scrollFrameTo);
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
        <Tooltip label={reportOnly ? 'Show the editing panel' : 'The report only'} withArrow>
          <ActionIcon
            size="lg"
            variant={reportOnly ? 'light' : 'default'}
            onClick={() => setReportOnly((on) => !on)}
            aria-label={reportOnly ? 'Show the editing panel' : 'Show the report only'}
            aria-pressed={reportOnly}
            data-testid="report-only-toggle"
          >
            {reportOnly ? (
              <PanelLeftOpen size={17} strokeWidth={STROKE} />
            ) : (
              <PanelLeftClose size={17} strokeWidth={STROKE} />
            )}
          </ActionIcon>
        </Tooltip>
        <Button
          size="sm"
          variant="default"
          leftSection={<Settings2 size={17} strokeWidth={STROKE} />}
          disabled={!layer}
          onClick={() => setSettingsOpen(true)}
          data-testid="report-settings-open"
        >
          Report settings
        </Button>
        {layer && (
          <ReportSettingsModal
            opened={settingsOpen}
            onClose={() => setSettingsOpen(false)}
            layer={layer}
            onEdit={api.edit}
          />
        )}
        <Tooltip label={unavailable ?? 'The full render, with its PDF'} withArrow multiline maw={320}>
          <span>
            <Button
              size="sm"
              variant="default"
              leftSection={
                pdf.busy ? (
                  <DepictioRose mode="loading" size={17} label="" />
                ) : (
                  <FileDown size={17} strokeWidth={STROKE} />
                )
              }
              aria-busy={pdf.busy || undefined}
              disabled={pdf.busy || !layer || conflict || Boolean(unavailable)}
              onClick={pdf.run}
              data-testid="report-exact-pdf"
            >
              Exact PDF
            </Button>
          </span>
        </Tooltip>
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
    if (serverInfoLoading && !enabled) return centered(<DepictioRose mode="loading" size={64} />);
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
    if (api.loading && !layer) return centered(<DepictioRose mode="loading" size={64} />);
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
      <TabLinkProvider tabs={family}>
      <SnapshotContext.Provider value={snapshotSource}>
        <div
          className="re-body"
          ref={bodyRef}
          data-testid="report-editor"
          data-report-only={reportOnly || undefined}
          style={{ '--re-split': `${split.ratio}fr`, '--re-split-rest': `${1 - split.ratio}fr` } as React.CSSProperties}
        >
          <div className="re-edit" ref={editColumnRef} data-testid="report-edit-column">
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
          <div
            className="re-splitter"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the structure and the preview"
            aria-valuemin={Math.round(split.min * 100)}
            aria-valuemax={Math.round(split.max * 100)}
            aria-valuenow={Math.round(split.ratio * 100)}
            tabIndex={0}
            title="Drag to resize, double-click to reset"
            onPointerDown={split.onPointerDown}
            onKeyDown={split.onKeyDown}
            onDoubleClick={split.reset}
            data-testid="report-splitter"
          />
          <div className="re-preview">
            <PreviewPane
              job={job}
              bridge={bridge}
              scheme={scheme}
              syncScroll={syncScroll}
              onToggleSync={() => setSyncScroll((on) => !on)}
              unavailable={unavailable}
            />
          </div>
        </div>
      </SnapshotContext.Provider>
      </TabLinkProvider>
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

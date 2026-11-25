import React, { useEffect, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  downloadNotebookRender,
  exportNotebook,
  fetchNotebookPreflight,
  fetchNotebookRenderStatus,
  humanizeKind,
  publicBundleDownloadUrl,
  startNotebookRender,
  type AnalysisState,
  type CombinedDefaultView,
  type NotebookInclusion,
  type NotebookPreflight,
  type NotebookRenderStatus,
  type NotebookPdfStyle,
  type NotebookTheme,
  Z_LAYERS,
} from 'depictio-react-core';
import { useReportEditorEnabled } from '../hooks/useReportEditorEnabled';
import TileSummary, { type TileGroup, type TileStatus } from '../components/export/TileSummary';
import { usePublicCopy } from '../components/publicDownload/PublicCopy';
import { formatBuiltAt, formatBundleBytes } from '../components/publicDownload/format';

/**
 * Export the dashboard: preflight first (what each tile becomes, with a reason
 * written for the reader), then the file.
 *
 * Three outputs, as three cards (#1480): the combined file (the rendered
 * report AND the interactive dashboard in one HTML, behind a "Report |
 * Dashboard" switch), the report alone, and the `.qmd` source. The `.qmd` is
 * generated text the reader renders themselves; the two rendered outputs are
 * that same document executed here — on a worker, over minutes, so they are
 * started, polled, then downloaded. A card this reader cannot have is dimmed
 * with the reason (no Quarto here, a copy whose code is not the project's...)
 * and the modal opens on the notebook instead. The dashboard alone is a link
 * under the cards, to its own modal.
 */
interface NotebookExportModalProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  dashboardTitle?: string;
  getAnalysisState: () => AnalysisState;
  /** Whether the combined file is offered at all: false where the server has
   *  the static export switched off, and the choice is then not shown. */
  combinedOffered?: boolean;
  /** Which output the modal opens on (the combined file by default). */
  initialOutput?: ExportChoice;
  /** Opens the dashboard-only export (the static bundle's own modal). */
  onExportDashboardOnly?: () => void;
  /** The reader may edit this dashboard's report: the link to the editor
   *  shows only then (the editor answers 404 to anyone else). */
  canEditReport?: boolean;
}

/** What the notebook makes of a tile, for the tile list. */
const TILE_STATUSES: Record<NotebookInclusion, TileStatus> = {
  code: { label: 'recomputed as code', color: 'teal' },
  api: { label: 'drawn by Depictio', color: 'blue' },
  omitted: { label: 'left out', color: 'gray' },
};
const TILE_ORDER: NotebookInclusion[] = ['code', 'api', 'omitted'];

/** The combined file, the report alone, or the document. */
export type ExportChoice = 'combined' | 'report' | 'qmd';

const FORMATS: { value: ExportChoice; title: string; icon: string; hint: string }[] = [
  {
    value: 'combined',
    title: 'Report + dashboard',
    icon: 'mdi:file-document-multiple-outline',
    hint: 'One HTML file: the report, and the interactive dashboard one click away.',
  },
  {
    value: 'report',
    title: 'Report',
    icon: 'mdi:file-document-outline',
    hint: 'Rendered here as HTML, with a PDF if you want one.',
  },
  {
    value: 'qmd',
    title: 'Notebook',
    icon: 'mdi:notebook-outline',
    hint: 'The Quarto document (.qmd) to run and edit yourself.',
  },
];

const PRIMARY_LABEL: Record<ExportChoice, string> = {
  combined: 'Build report + dashboard',
  report: 'Render report',
  qmd: 'Download notebook',
};

/** One filter value in plain words: a range as "a to b", a list cut at three. */
function filterValue(value: unknown, type?: string | null): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    if (value.length === 2 && /range|slider/i.test(type ?? '')) {
      return `${String(value[0])} to ${String(value[1])}`;
    }
    const head = value.slice(0, 3).map(String).join(', ');
    return value.length > 3 ? `${head} +${value.length - 3}` : head;
  }
  return String(value);
}

/** The state the export is drawn at, as pills: "Island: Biscoe", "2 groups".
 *  Empty when the reader exports the dashboard as it opens. */
function statePills(state: AnalysisState | null): string[] {
  if (!state) return [];
  const label = (name: string) =>
    name ? name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ') : name;
  const filters = state.filters
    .map((f) => {
      const value = filterValue(f.value, f.interactive_component_type);
      return value ? `${label(f.column_name || f.metadata?.column_name || f.index)}: ${value}` : null;
    })
    .filter((f): f is string => Boolean(f));
  const groups = state.groups.length
    ? [`${state.groups.length} selection group${state.groups.length === 1 ? '' : 's'}`]
    : [];
  return [...filters, ...groups];
}

/** A format to choose: selected, or dimmed with why it is not available (the
 *  footnote is short, the whole reason is on hover). */
const FormatCard: React.FC<{
  title: string;
  icon: string;
  hint: string;
  selected: boolean;
  unavailable?: string | null;
  onSelect: () => void;
  testId: string;
}> = ({ title, icon, hint, selected, unavailable, onSelect, testId }) => (
  <Tooltip
    label={unavailable ?? ''}
    disabled={!unavailable}
    multiline
    w={300}
    zIndex={Z_LAYERS.tooltip}
  >
    <UnstyledButton
      onClick={onSelect}
      disabled={Boolean(unavailable)}
      aria-pressed={selected}
      data-testid={testId}
      data-selected={selected || undefined}
      data-unavailable={unavailable ? true : undefined}
      style={{ cursor: unavailable ? 'not-allowed' : 'pointer', display: 'block', height: '100%' }}
    >
      <Paper
        withBorder
        radius="md"
        p="sm"
        h="100%"
        style={{
          opacity: unavailable ? 0.55 : 1,
          borderColor: selected ? 'var(--mantine-primary-color-filled)' : undefined,
          background: selected ? 'var(--mantine-primary-color-light)' : undefined,
        }}
      >
        <Stack gap={8}>
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <ThemeIcon variant={selected ? 'filled' : 'light'} size={32} radius="md">
              <Icon icon={icon} width={18} />
            </ThemeIcon>
            {selected && <Icon icon="mdi:check-circle" width={18} color="var(--mantine-primary-color-filled)" />}
          </Group>
          <Stack gap={2}>
            <Text size="sm" fw={600}>
              {title}
            </Text>
            <Text size="xs" c="dimmed" lh={1.35}>
              {unavailable ? 'Not available to you here' : hint}
            </Text>
          </Stack>
        </Stack>
      </Paper>
    </UnstyledButton>
  </Tooltip>
);

const THEME_HINT: Record<NotebookTheme, string> = {
  paper: "Depictio's Paper look, in this instance's brand colour, with Inter embedded.",
  classic: "Quarto's stock page and Plotly's own figures.",
};

/** What the worker is doing, in the reader's words. */
function phaseLabel(phase?: string | null): string {
  switch (phase) {
    case 'embedding':
      return 'Packing the dashboard';
    case 'combining':
      return 'Putting the report and the dashboard together';
    case 'storing':
      return 'Saving';
    default:
      return 'Rendering';
  }
}

function elapsedLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

const NotebookExportModal: React.FC<NotebookExportModalProps> = ({
  opened,
  onClose,
  dashboardId,
  dashboardTitle,
  getAnalysisState,
  initialOutput = 'combined',
  combinedOffered = true,
  onExportDashboardOnly,
  canEditReport = false,
}) => {
  const reportEditorEnabled = useReportEditorEnabled() && canEditReport;
  // The visitors' ready copy (#1480): the report + dashboard file and its PDF,
  // already rendered at the default view.
  const publicCopy = usePublicCopy(opened ? dashboardId : null);
  const [state, setState] = useState<AnalysisState | null>(null);
  const [preflight, setPreflight] = useState<NotebookPreflight | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<ExportChoice>(initialOutput);
  const [defaultView, setDefaultView] = useState<CombinedDefaultView>('report');
  const [theme, setTheme] = useState<NotebookTheme>('paper');
  // Advanced: a PDF beside the HTML report (off by default).
  const [pdf, setPdf] = useState(false);
  const [pdfStyle, setPdfStyle] = useState<NotebookPdfStyle>('colour');
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);
  const [job, setJob] = useState<NotebookRenderStatus | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!opened) return;
    const snapshot = getAnalysisState();
    setState(snapshot);
    setPreflight(null);
    setError(null);
    setDownloaded(null);
    setJob(null);
    setStartedAt(null);
    setFormat(initialOutput);
    const controller = new AbortController();
    fetchNotebookPreflight(dashboardId, snapshot, controller.signal)
      .then((res) => {
        setPreflight(res);
        // An output this reader may not have: the notebook is what they can take.
        const refused = !res.render_available || Boolean(res.render_reason);
        setFormat((f) =>
          (f === 'report' && refused) || (f === 'combined' && (refused || !res.combined_available))
            ? 'qmd'
            : f,
        );
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => controller.abort();
    // The snapshot is taken once per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, dashboardId]);

  // A render is a job on a worker: ask it where it is until it stops moving.
  useEffect(() => {
    if (!job || job.status === 'ready' || job.status === 'error') return;
    const controller = new AbortController();
    const tick = window.setInterval(
      () => setElapsed(startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0),
      1000,
    );
    const poll = window.setInterval(() => {
      fetchNotebookRenderStatus(job.job_id, controller.signal)
        .then((next) =>
          setJob((prev) =>
            prev && prev.job_id === next.job_id
              ? { ...next, filename: next.filename ?? prev.filename }
              : prev,
          ),
        )
        .catch((err) => {
          if (!controller.signal.aborted) {
            setError(err instanceof Error ? err.message : String(err));
          }
        });
    }, 3000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
      controller.abort();
    };
  }, [job, startedAt]);

  const handleDownload = async () => {
    if (!state) return;
    setDownloading(true);
    setError(null);
    try {
      const filename = await exportNotebook(dashboardId, state, theme, pdf, pdfStyle);
      setDownloaded(filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  };

  const handleRender = async () => {
    if (!state) return;
    setDownloading(true);
    setError(null);
    setDownloaded(null);
    try {
      const started = await startNotebookRender(dashboardId, state, theme, {
        output: format === 'combined' ? 'combined' : 'report',
        defaultView,
        pdf,
        pdfStyle,
      });
      setStartedAt(Date.now());
      setElapsed(0);
      setJob(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  };

  const handleDownloadReport = async (which: 'html' | 'pdf' = 'html') => {
    if (!job) return;
    setDownloading(true);
    setError(null);
    try {
      setDownloaded(await downloadNotebookRender(job.job_id, which));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  };

  // The server renders reports, but not for this reader (a guest on a copy
  // whose code is not the project's): said on the card, before the click.
  const renderReason = preflight?.render_available ? (preflight?.render_reason ?? null) : null;
  const renderAvailable = (preflight?.render_available ?? false) && !renderReason;
  const counts = preflight?.counts ?? {};
  const isCombined = format === 'combined';
  // Both rendered outputs run the same job; only what it produces differs.
  const isReport = format === 'report' || isCombined;
  const handleDashboardOnly = () => {
    onClose();
    onExportDashboardOnly?.();
  };
  const rendering = Boolean(job && job.status !== 'ready' && job.status !== 'error');

  // Why a card cannot be chosen; nothing while the preflight is out.
  const unavailable: Record<ExportChoice, string | null> = {
    report: !preflight
      ? null
      : (renderReason ?? (renderAvailable ? null : 'Rendered reports are off on this server.')),
    combined: !preflight
      ? null
      : (renderReason ??
        (preflight.combined_available
          ? null
          : preflight.combined_reason
            ? `Not here: ${preflight.combined_reason}.`
            : 'This server cannot produce it.')),
    qmd: null,
  };
  const formats = FORMATS.filter((f) => f.value !== 'combined' || combinedOffered);

  // The tiles, by tab in the dashboard's order.
  const tileGroups: TileGroup[] = [];
  for (const c of preflight?.components ?? []) {
    const tab = c.tab || 'Tiles';
    let group = tileGroups.find((g) => g.id === tab);
    if (!group) {
      group = { id: tab, title: tab, items: [] };
      tileGroups.push(group);
    }
    const note = [
      c.reason,
      c.output === 'snapshot' ? 'Shipped as a snapshot.' : null,
      c.name ? `Function: ${c.name}` : null,
    ]
      .filter(Boolean)
      .join(' ');
    group.items.push({
      id: c.index,
      title: c.title || c.index,
      kind: humanizeKind(c.kind || c.component_type),
      status: c.status,
      note: note || null,
    });
  }
  const total = preflight?.components.length ?? 0;
  const stages = counts.stages ?? 0;
  const summary = [
    `${total} tile${total === 1 ? '' : 's'}`,
    (counts.native ?? 0) > 0 ? `${counts.native} drawn in the document` : null,
    (counts.snapshot ?? 0) > 0 ? `${counts.snapshot} as snapshots` : null,
    stages > 0 ? `${stages} filter stage${stages === 1 ? '' : 's'}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  const pills = statePills(state);
  // The ready copy is this very file when the reader exports the default view.
  const readyReport = publicCopy?.report?.available ? publicCopy.report : null;
  const readyIsThisView = Boolean(readyReport) && pills.length === 0 &&
    !readyReport?.rebuilding &&
    // An owner sees whether the copy still matches the dashboard and data.
    publicCopy?.fresh !== false;

  const primaryDisabled =
    !state || !preflight || Boolean(unavailable[format]) || (isReport && !renderAvailable);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      // Opened from the settings modal, so it must stack above it: at Mantine's
      // default it rendered underneath and the settings caught every click.
      zIndex={Z_LAYERS.nestedOverlay}
      size="lg"
      title={
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon variant="light" size={36} radius="md">
            <Icon icon="mdi:export-variant" width={20} />
          </ThemeIcon>
          <Stack gap={0}>
            <Text fw={600} lh={1.2}>
              Export as a report
            </Text>
            <Text size="xs" c="dimmed" lh={1.3}>
              {dashboardTitle || 'This dashboard'}
            </Text>
          </Stack>
        </Group>
      }
      styles={{ header: { alignItems: 'flex-start' } }}
    >
      <Stack gap="md" data-testid="notebook-export-modal">
        <Group gap={6} data-testid="notebook-export-state">
          <Text size="xs" c="dimmed" fw={500}>
            {pills.length ? 'Your view:' : 'Your view: the dashboard as it opens'}
          </Text>
          {pills.map((p) => (
            <Badge
              key={p}
              size="sm"
              variant="light"
              color="gray"
              radius="sm"
              style={{ textTransform: 'none', fontWeight: 500 }}
            >
              {p}
            </Badge>
          ))}
        </Group>

        <Stack gap={6}>
          <SimpleGrid cols={{ base: 1, xs: formats.length }} spacing="sm">
            {formats.map((f) => (
              <FormatCard
                key={f.value}
                title={f.title}
                icon={f.icon}
                hint={f.hint}
                selected={format === f.value}
                unavailable={unavailable[f.value]}
                onSelect={() => setFormat(f.value)}
                testId={`export-format-${f.value}`}
              />
            ))}
          </SimpleGrid>
          {readyReport && format !== 'qmd' && !job && (
            <Paper withBorder radius="md" px="sm" py={8} data-testid="notebook-export-ready-copy">
              <Stack gap={6}>
                <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                  <Icon icon="mdi:lightning-bolt-outline" width={18} style={{ flexShrink: 0 }} />
                  <Text size="xs" style={{ minWidth: 0 }}>
                    {readyIsThisView ? (
                      <>
                        <b>Ready now.</b> Your view is the default one: its report + dashboard
                        is already built, no render needed.
                      </>
                    ) : (
                      <>
                        <b>Ready copy</b> at the default view
                        {readyReport.built_at ? `, built ${formatBuiltAt(readyReport.built_at)}` : ''}
                        . Your filters need a render.
                      </>
                    )}
                  </Text>
                </Group>
                <Group gap={6} wrap="wrap" pl={26}>
                  <Button
                    component="a"
                    href={publicBundleDownloadUrl(dashboardId, 'report')}
                    download
                    size="xs"
                    variant={readyIsThisView ? 'filled' : 'light'}
                    leftSection={<Icon icon="mdi:download" width={14} />}
                    data-testid="notebook-export-ready-html"
                  >
                    Report + dashboard{readyReport.size_bytes ? ` · ${formatBundleBytes(readyReport.size_bytes)}` : ''}
                  </Button>
                  {readyReport.pdf_available && (
                    <Button
                      component="a"
                      href={publicBundleDownloadUrl(dashboardId, 'pdf')}
                      download
                      size="xs"
                      variant="light"
                      leftSection={<Icon icon="mdi:file-pdf-box" width={14} />}
                      data-testid="notebook-export-ready-pdf"
                    >
                      PDF
                      {readyReport.pdf_size_bytes
                        ? ` · ${formatBundleBytes(readyReport.pdf_size_bytes)}`
                        : ''}
                    </Button>
                  )}
                </Group>
              </Stack>
            </Paper>
          )}
          {/* The PDF is one of the outputs, not a detail of the look: it sits
              with the formats. */}
          <Paper withBorder radius="md" px="sm" py={8} data-testid="notebook-export-pdf-row">
            <Group justify="space-between" wrap="nowrap" gap="sm">
              <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                <Icon icon="mdi:file-pdf-box" width={18} style={{ flexShrink: 0 }} />
                <Stack gap={0} style={{ minWidth: 0 }}>
                  <Text size="sm" fw={500}>
                    Also a PDF
                  </Text>
                  <Text size="xs" c="dimmed">
                    {pdf
                      ? pdfStyle === 'colour'
                        ? 'Figures as images, tables as their first rows; tab colours on headings.'
                        : 'Figures as images, tables as their first rows; print-friendly text.'
                      : 'Figures as images, tables as their first rows, ready to print.'}
                  </Text>
                </Stack>
              </Group>
              <Group gap="xs" wrap="nowrap">
                {pdf && (
                  <SegmentedControl
                    size="xs"
                    value={pdfStyle}
                    onChange={(v) => setPdfStyle(v as NotebookPdfStyle)}
                    data={[
                      { label: 'Colour', value: 'colour' },
                      { label: 'Mono', value: 'mono' },
                    ]}
                    data-testid="notebook-export-pdf-style"
                  />
                )}
                <Switch
                  checked={pdf}
                  onChange={(e) => setPdf(e.currentTarget.checked)}
                  aria-label="Also a PDF"
                  data-testid="notebook-export-pdf"
                />
              </Group>
            </Group>
          </Paper>
          {reportEditorEnabled && (
            <Anchor
              size="xs"
              href={`/dashboard-report/${dashboardId}`}
              data-testid="notebook-export-edit-report"
            >
              Edit the report: cover, introduction, captions…
            </Anchor>
          )}
        </Stack>

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
          <Stack gap="xs">
            <Group justify="space-between" align="baseline" wrap="nowrap">
              <Text size="sm" fw={600}>
                What the document holds
              </Text>
              <Text size="xs" c="dimmed" data-testid="notebook-export-counts">
                {summary}
              </Text>
            </Group>
            <ScrollArea.Autosize mah={260} type="auto">
              <TileSummary
                groups={tileGroups}
                statuses={TILE_STATUSES}
                order={TILE_ORDER}
                testId="notebook-export-tiles"
                itemTestId="notebook-export-row"
              />
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
          </Stack>
        )}

        <Accordion variant="contained" radius="md" data-testid="notebook-export-advanced">
          <Accordion.Item value="appearance">
            <Accordion.Control icon={<Icon icon="mdi:palette-outline" width={18} />}>
              <Text size="sm" fw={500}>
                Appearance
              </Text>
              <Text size="xs" c="dimmed">
                {theme === 'paper' ? 'Paper' : 'Classic'}
                {isCombined ? ` · opens on the ${defaultView}` : ''}
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Stack gap={4}>
                  <Text fw={500} size="sm">
                    Look
                  </Text>
                  <SegmentedControl
                    value={theme}
                    onChange={(v) => setTheme(v as NotebookTheme)}
                    data={[
                      { label: 'Paper', value: 'paper' },
                      { label: 'Classic', value: 'classic' },
                    ]}
                    data-testid="notebook-export-theme"
                  />
                  <Text size="xs" c="dimmed">
                    {THEME_HINT[theme]}
                  </Text>
                </Stack>
                {isCombined && (
                  <Stack gap={4}>
                    <Text fw={500} size="sm">
                      Opens on
                    </Text>
                    <SegmentedControl
                      value={defaultView}
                      onChange={(v) => setDefaultView(v as CombinedDefaultView)}
                      data={[
                        { label: 'Report', value: 'report' },
                        { label: 'Dashboard', value: 'dashboard' },
                      ]}
                      data-testid="export-default-view"
                    />
                    <Text size="xs" c="dimmed">
                      The view the file shows first; a reader's own choice is remembered after
                      that, and links can open either (<code>#dashboard</code>,{' '}
                      <code>#report</code>).
                    </Text>
                  </Stack>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

        {job && rendering && (
          <Alert color="blue" variant="light" data-testid="notebook-export-rendering">
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm">
                {job.status === 'queued' ? 'Queued' : phaseLabel(job.phase)} · {elapsedLabel(elapsed)}
              </Text>
            </Group>
          </Alert>
        )}

        {job?.status === 'error' && (
          <Alert color="red" title="Render failed" data-testid="notebook-export-render-error">
            {job.reason || 'The worker could not render this document.'}
          </Alert>
        )}

        {job?.status === 'ready' && !downloaded && (
          <Alert color="teal" variant="light" data-testid="notebook-export-render-ready">
            <code>{job.filename}</code> is ready
            {job.size ? ` (${(job.size / 1e6).toFixed(1)} MB)` : ''}, built in{' '}
            {elapsedLabel(elapsed)}.
            {job.pdf_error && ` The PDF could not be made: ${job.pdf_error}`}
          </Alert>
        )}

        {downloaded && (
          <Alert color="teal" variant="light" data-testid="notebook-export-done">
            Downloaded <code>{downloaded}</code>.
            {!isReport && (
              <>
                {' '}
                Set <code>DEPICTIO_API_URL</code> and <code>DEPICTIO_API_TOKEN</code> (a
                long-lived token from the CLI agents page) before running it.
              </>
            )}
          </Alert>
        )}

        <Group justify="space-between" wrap="nowrap" gap="sm">
          <Group gap="lg" style={{ minWidth: 0 }}>
            {onExportDashboardOnly && (
              <Anchor
                component="button"
                type="button"
                size="xs"
                onClick={handleDashboardOnly}
                data-testid="export-dashboard-only"
              >
                The dashboard alone (offline HTML)…
              </Anchor>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Button variant="default" onClick={onClose}>
              Close
            </Button>
            {isReport && job?.status !== 'ready' ? (
              <Tooltip
                label="Rendered on the server: about a minute or more. You can leave this open."
                disabled={!isReport || Boolean(job) || !renderAvailable}
                zIndex={Z_LAYERS.tooltip}
              >
              <Button
                leftSection={<Icon icon="mdi:file-document-outline" width={16} />}
                onClick={handleRender}
                loading={downloading || rendering}
                disabled={primaryDisabled}
                variant={readyIsThisView ? 'default' : 'filled'}
                data-testid="notebook-export-render"
              >
                {job?.status === 'error' ? 'Render again' : PRIMARY_LABEL[format]}
              </Button>
              </Tooltip>
            ) : (
              <>
                {isReport && job?.pdf_filename && (
                  <Button
                    variant="default"
                    leftSection={<Icon icon="mdi:file-pdf-box" width={16} />}
                    onClick={() => handleDownloadReport('pdf')}
                    loading={downloading}
                    data-testid="notebook-export-download-pdf"
                  >
                    Download PDF
                  </Button>
                )}
                <Button
                  leftSection={<Icon icon="mdi:download" width={16} />}
                  onClick={isReport ? () => handleDownloadReport('html') : handleDownload}
                  loading={downloading}
                  disabled={!state || !preflight}
                  data-testid="notebook-export-download"
                >
                  {isCombined ? 'Download file' : isReport ? 'Download report' : PRIMARY_LABEL.qmd}
                </Button>
              </>
            )}
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default NotebookExportModal;

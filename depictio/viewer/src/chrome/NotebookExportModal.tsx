import React, { useEffect, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Checkbox,
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
  downloadNotebookRender,
  exportNotebook,
  fetchNotebookPreflight,
  fetchNotebookRenderStatus,
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

/**
 * Export the dashboard: preflight first (what each tile becomes, with a reason
 * written for the reader), then the file.
 *
 * The default is the combined file: the rendered report AND the interactive
 * dashboard in one HTML, behind a "Report | Dashboard" switch. The separate
 * outputs sit under "Advanced": the dashboard alone (the static bundle, its
 * own modal), the report alone, and the `.qmd` source. The `.qmd` is generated
 * text the reader renders themselves; the two rendered outputs are that same
 * document executed here — on a worker, over minutes, so they are started,
 * polled, then downloaded. Where this server cannot produce the combined file
 * (no Quarto, or the caller may not embed the data), the default falls back to
 * the dashboard alone and says why.
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

const STATUS_META: Record<NotebookInclusion, { label: string; color: string }> = {
  code: { label: 'as code', color: 'teal' },
  api: { label: 'via Depictio', color: 'blue' },
  omitted: { label: 'omitted', color: 'gray' },
};

/** The combined file, the report alone, or the document. */
export type ExportChoice = 'combined' | 'report' | 'qmd';

const FORMAT_HINT: Record<ExportChoice, string> = {
  combined:
    'One HTML file: the rendered report and the interactive dashboard, with a Report | ' +
    'Dashboard switch. Opens without a server.',
  qmd: 'The document to render yourself: quarto render <file>.qmd',
  report: 'That same document, rendered here: one HTML file, nothing to install.',
};

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

  const renderAvailable = preflight?.render_available ?? false;
  const combinedAvailable = preflight?.combined_available ?? false;
  const counts = preflight?.counts ?? {};
  const isCombined = format === 'combined';
  // Both rendered outputs run the same job; only what it produces differs.
  const isReport = format === 'report' || isCombined;
  // The default cannot be made here: it falls back to the dashboard alone.
  const combinedFallback = isCombined && Boolean(preflight) && !combinedAvailable;
  const handleDashboardOnly = () => {
    onClose();
    onExportDashboardOnly?.();
  };
  const rendering = Boolean(job && job.status !== 'ready' && job.status !== 'error');

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      // Opened from the settings modal, so it must stack above it: at Mantine's
      // default it rendered underneath and the settings caught every click.
      zIndex={Z_LAYERS.nestedOverlay}
      size="lg"
      title={
        <Group gap="xs">
          <Icon icon="mdi:export-variant" width={20} />
          <Text fw={600}>Export</Text>
        </Group>
      }
    >
      <Stack gap="md" data-testid="notebook-export-modal">
        <Text size="sm" c="dimmed">
          {dashboardTitle ? `"${dashboardTitle}"` : 'This dashboard'}, every tab, with the
          filters, funnel order and groups you have right now.{' '}
          {isCombined
            ? 'One file to send: the rendered report, and the whole interactive dashboard one ' +
              'click away. Filters set in either view follow in the other.'
            : 'As a Quarto document you can keep working in: each tile is reproduced as code ' +
              'where it can be, and rendered through Depictio otherwise.'}
        </Text>

        {reportEditorEnabled && (
          <Group gap={6} data-testid="notebook-export-edit-report">
            <Icon icon="mdi:file-document-edit-outline" width={16} />
            <Anchor size="sm" href={`/dashboard-report/${dashboardId}`}>
              Edit the report…
            </Anchor>
            <Text size="xs" c="dimmed">
              Cover, introduction, captions and what each tile contributes.
            </Text>
          </Group>
        )}

        {combinedFallback && (
          <Alert
            color="yellow"
            variant="light"
            title="Report + dashboard is not available here"
            data-testid="export-combined-fallback"
          >
            <Stack gap="xs">
              <Text size="sm">
                {preflight?.combined_reason
                  ? `Why: ${preflight.combined_reason}.`
                  : 'This server cannot produce it.'}
                {/* Offered only where the dashboard-only export is (its owner):
                    a non-owner was sent to an export that then failed. */}
                {onExportDashboardOnly &&
                  ' The dashboard alone still exports as one offline HTML file.'}
              </Text>
            </Stack>
          </Alert>
        )}

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
              {(counts.native ?? 0) > 0 && (
                <Badge color="cyan" variant="light">
                  {counts.native} drawn in the document
                </Badge>
              )}
              {(counts.snapshot ?? 0) > 0 && (
                <Badge color="grape" variant="light">
                  {counts.snapshot} as snapshot
                </Badge>
              )}
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
                          <Tooltip
                            label={c.reason ?? ''}
                            disabled={!c.reason}
                            multiline
                            w={320}
                            zIndex={Z_LAYERS.tooltip}
                          >
                            <Group gap={6} wrap="nowrap">
                              <Badge size="xs" color={meta.color} variant="light">
                                {meta.label}
                              </Badge>
                              {c.output === 'snapshot' && (
                                <Badge size="xs" color="grape" variant="outline">
                                  snapshot
                                </Badge>
                              )}
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

        {isCombined && !combinedFallback && (
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
              The view the file shows first; a reader's own choice is remembered after that, and
              links can open either (<code>#dashboard</code>, <code>#report</code>).
            </Text>
          </Stack>
        )}

        <Accordion
          variant="contained"
          defaultValue={initialOutput === 'combined' ? null : 'advanced'}
          data-testid="export-advanced-panel"
        >
          <Accordion.Item value="advanced">
            <Accordion.Control data-testid="export-advanced-toggle">
              <Text size="sm" fw={500}>
                Advanced: separate outputs
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <SegmentedControl
                  value={format}
                  onChange={(v) => setFormat(v as ExportChoice)}
                  data={[
                    ...(combinedOffered
                      ? [
                          {
                            label: 'Report + dashboard',
                            value: 'combined',
                            disabled: !combinedAvailable,
                          },
                        ]
                      : []),
                    { label: 'Report only', value: 'report', disabled: !renderAvailable },
                    { label: 'Quarto source (.qmd)', value: 'qmd' },
                  ]}
                  data-testid="notebook-export-format"
                />
                <Text size="xs" c="dimmed">
                  {FORMAT_HINT[format]}
                  {!renderAvailable && ' Rendered reports are off on this server.'}
                </Text>
                {onExportDashboardOnly && (
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="default"
                      leftSection={<Icon icon="mdi:view-dashboard-outline" width={14} />}
                      onClick={handleDashboardOnly}
                      data-testid="export-dashboard-only"
                    >
                      Dashboard only…
                    </Button>
                    <Text size="xs" c="dimmed">
                      The interactive dashboard alone, as one offline HTML file (owners).
                    </Text>
                  </Group>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

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

        <Accordion variant="contained" radius="md" data-testid="notebook-export-advanced">
          <Accordion.Item value="advanced">
            <Accordion.Control>
              <Text size="sm" fw={500}>
                Advanced
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              <Checkbox
                checked={pdf}
                onChange={(e) => setPdf(e.currentTarget.checked)}
                label="Also a PDF"
                description={
                  'Rendered beside the HTML report with Quarto (typst, no TeX): figures as ' +
                  'images, tables as their first rows, filters and other interactive parts left out.'
                }
                data-testid="notebook-export-pdf"
              />
              <Stack gap={4} mt="sm">
                <Text size="sm" fw={500} c={pdf ? undefined : 'dimmed'}>
                  PDF colours
                </Text>
                <SegmentedControl
                  value={pdfStyle}
                  onChange={(v) => setPdfStyle(v as NotebookPdfStyle)}
                  disabled={!pdf}
                  data={[
                    { label: 'Colour', value: 'colour' },
                    { label: 'Monochrome', value: 'mono' },
                  ]}
                  data-testid="notebook-export-pdf-style"
                />
                <Text size="xs" c="dimmed">
                  {pdfStyle === 'colour'
                    ? 'Tab colours on headings and in the contents, tinted notes.'
                    : 'Print-friendly: headings, contents and notes in the text colour. Figures keep theirs.'}
                </Text>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

        {isReport && !job && renderAvailable && !combinedFallback && (
          <Alert color="blue" variant="light" data-testid="notebook-export-render-hint">
            The Quarto document, executed on the server: every tile is recomputed and every
            rendered figure costs a browser pass, so a dashboard this size takes a few minutes.
            You can leave this open while it builds.
          </Alert>
        )}

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

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Close
          </Button>
          {combinedFallback && !job ? (
            onExportDashboardOnly ? (
              <Button
                leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
                onClick={handleDashboardOnly}
                data-testid="export-dashboard-only-primary"
              >
                Export dashboard only
              </Button>
            ) : null
          ) : isReport && job?.status !== 'ready' ? (
            <Button
              leftSection={<Icon icon="mdi:file-document-outline" width={16} />}
              onClick={handleRender}
              loading={downloading || rendering}
              disabled={
                !state || !preflight || (isCombined ? !combinedAvailable : !renderAvailable)
              }
              data-testid="notebook-export-render"
            >
              {job?.status === 'error'
                ? 'Render again'
                : isCombined
                  ? 'Build report + dashboard'
                  : 'Render report'}
            </Button>
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
                {isCombined ? 'Download file' : isReport ? 'Download report' : 'Download'}
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default NotebookExportModal;

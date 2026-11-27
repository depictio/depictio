import React, { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  getPublicBundleStatus,
  publicBundleDownloadUrl,
  type AnalysisState,
  type PublicBundleStatus,
  type PublicCopyFile,
} from 'depictio-react-core';
import { formatBuiltAt, formatBundleBytes } from '../publicDownload/format';

/**
 * Ready copy or my view (#1480): the export modals open on the copy a public
 * project keeps of each dashboard (built at its default view, downloaded at
 * once), and "My view" builds the reader's own (their filters, a render).
 */
export type CopyMode = 'copy' | 'view';

/** "Ready copy | My view", with light icons. `viewDisabled`: this reader
 *  cannot build their own (an anonymous visitor). */
export const CopyModeControl: React.FC<{
  value: CopyMode;
  onChange: (mode: CopyMode) => void;
  viewDisabled?: boolean;
}> = ({ value, onChange, viewDisabled = false }) => (
  <SegmentedControl
    fullWidth
    value={value}
    onChange={(v) => onChange(v as CopyMode)}
    data-testid="export-copy-mode"
    data={[
      {
        value: 'copy',
        label: (
          <Group gap={6} justify="center" wrap="nowrap">
            <Icon icon="tabler:bolt" width={16} />
            <span>Ready copy</span>
          </Group>
        ),
      },
      {
        value: 'view',
        disabled: viewDisabled,
        label: (
          <Group gap={6} justify="center" wrap="nowrap">
            <Icon icon="tabler:adjustments-horizontal" width={16} />
            <span>My view</span>
          </Group>
        ),
      },
    ]}
  />
);

/** A filter value in plain words: a range as "a to b", a list cut at three. */
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

/** The reader's view as pills ("Island: Biscoe", "2 selection groups"); empty
 *  when it is the dashboard as it opens. */
export function statePills(state: AnalysisState | null): string[] {
  if (!state) return [];
  const label = (name: string) =>
    name ? name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ') : name;
  const filters = state.filters
    .map((f) => {
      const value = filterValue(f.value, f.interactive_component_type);
      return value
        ? `${label(f.column_name || f.metadata?.column_name || f.index)}: ${value}`
        : null;
    })
    .filter((f): f is string => Boolean(f));
  const groups = state.groups.length
    ? [`${state.groups.length} selection group${state.groups.length === 1 ? '' : 's'}`]
    : [];
  return [...filters, ...groups];
}

/** "Your view: [Island: Biscoe] [Sex: male]", or that they are left out of a
 *  ready copy. */
export const ViewPills: React.FC<{ pills: string[]; applied: boolean }> = ({
  pills,
  applied,
}) => (
  <Group gap={6} data-testid="export-view-pills">
    <Text size="xs" c="dimmed" fw={500}>
      {pills.length === 0
        ? 'Your view: the dashboard as it opens'
        : applied
          ? 'Your view:'
          : 'Not in the ready copy:'}
    </Text>
    {pills.map((p) => (
      <Badge
        key={p}
        size="sm"
        variant="light"
        color="gray"
        radius="sm"
        style={{ textTransform: 'none', fontWeight: 500, opacity: applied ? 1 : 0.7 }}
      >
        {p}
      </Badge>
    ))}
  </Group>
);

export interface ReadyFile {
  file: PublicCopyFile;
  title: string;
  icon: string;
  sizeBytes?: number | null;
  /** The one the reader came for: a filled button. */
  primary?: boolean;
}

/** The ready files with their download buttons, and when they were built. */
export const ReadyCopyPanel: React.FC<{
  dashboardId: string;
  status: PublicBundleStatus;
  files: ReadyFile[];
}> = ({ dashboardId, status, files }) => {
  // The date of the file the reader came for: the report is rendered after
  // the dashboard bundle it embeds.
  const built = formatBuiltAt(
    files[0]?.file === 'dashboard' ? status.built_at : (status.report?.built_at ?? status.built_at),
  );
  // A report still on its first render is not "a newer copy": the card says
  // it is on its way (`ReadyCopyCard`).
  const rebuilding =
    status.rebuilding || (status.report?.available && status.report.rebuilding);
  return (
    <Stack gap="xs" data-testid="export-ready-copy">
      <Text size="xs" c="dimmed">
        Built{built ? ` ${built}` : ''} at the dashboard's default view: no filters, the
        Paper look. It downloads at once.
        {rebuilding ? ' A newer copy is being prepared.' : ''}
      </Text>
      <Stack gap={6}>
        {files.map((f) => {
          const size = formatBundleBytes(f.sizeBytes);
          return (
            <Paper key={f.file} withBorder radius="md" px="sm" py={8}>
              <Group justify="space-between" wrap="nowrap" gap="sm">
                <Group gap={10} wrap="nowrap" style={{ minWidth: 0 }}>
                  <Icon icon={f.icon} width={20} style={{ flexShrink: 0 }} />
                  <Text size="sm" fw={500} truncate>
                    {f.title}
                  </Text>
                </Group>
                <Button
                  component="a"
                  href={publicBundleDownloadUrl(dashboardId, f.file)}
                  download
                  size="xs"
                  variant={f.primary ? 'filled' : 'light'}
                  leftSection={<Icon icon="tabler:download" width={14} />}
                  data-testid={`export-ready-${f.file}`}
                >
                  {size ? `Download · ${size}` : 'Download'}
                </Button>
              </Group>
            </Paper>
          );
        })}
      </Stack>
    </Stack>
  );
};

/** How often the card asks again while a copy is being prepared. */
const PREPARING_POLL_MS = 30_000;

/**
 * The first thing the Export section offers where a public project keeps a
 * ready copy (#1480): its files as plain download links, nothing rendered for
 * the reader. While the report (or a newer copy) is being prepared the card
 * says so and asks again until it is there. Owners also read why a build
 * failed (the server sends `error` to them only).
 */
export const ReadyCopyCard: React.FC<{
  dashboardId: string;
  status: PublicBundleStatus;
}> = ({ dashboardId, status: initial }) => {
  const [status, setStatus] = useState(initial);
  useEffect(() => setStatus(initial), [initial]);
  const report = status.report;
  const preparing = Boolean(status.rebuilding || report?.rebuilding);
  useEffect(() => {
    if (!preparing) return;
    let alive = true;
    const timer = setTimeout(() => {
      void getPublicBundleStatus(dashboardId).then((s) => {
        if (alive && s?.available) setStatus(s);
      });
    }, PREPARING_POLL_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [dashboardId, status, preparing]);

  const reportPending = Boolean(report && !report.available && report.rebuilding);
  const reportError = report && !report.available && !report.rebuilding ? report.error : null;
  return (
    <Paper withBorder radius="md" p="sm" data-testid="export-ready-card">
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <ThemeIcon variant="light" size="lg" radius="md">
          <Icon icon="tabler:bolt" width={20} />
        </ThemeIcon>
        <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} size="sm">
            Ready to download
          </Text>
          <ReadyCopyPanel
            dashboardId={dashboardId}
            status={status}
            files={readyFiles(status, 'report')}
          />
          {reportPending && (
            <Group gap={8} wrap="nowrap" data-testid="export-ready-preparing">
              <Loader size={12} />
              <Text size="xs" c="dimmed" lh={1.35}>
                The report + dashboard file and its PDF are being prepared. They appear here
                when ready.
              </Text>
            </Group>
          )}
          {reportError && (
            <Text size="xs" c="red" lh={1.35} data-testid="export-ready-error">
              The report could not be built: {reportError}
            </Text>
          )}
        </Stack>
      </Group>
    </Paper>
  );
};

/** The ready files a public copy holds, the one for `primary` first. */
export function readyFiles(
  status: PublicBundleStatus,
  primary: PublicCopyFile,
): ReadyFile[] {
  const files: ReadyFile[] = [];
  const report = status.report?.available ? status.report : null;
  if (report) {
    files.push({
      file: 'report',
      title: 'Report + dashboard (HTML)',
      icon: 'tabler:file-text',
      sizeBytes: report.size_bytes,
    });
    if (report.pdf_available) {
      files.push({
        file: 'pdf',
        title: 'Report (PDF)',
        icon: 'tabler:file-type-pdf',
        sizeBytes: report.pdf_size_bytes,
      });
    }
  }
  files.push({
    file: 'dashboard',
    title: 'Dashboard only (HTML)',
    icon: 'tabler:layout-dashboard',
    sizeBytes: status.size_bytes,
  });
  const marked = files.map((f) => ({ ...f, primary: f.file === primary }));
  return [...marked.filter((f) => f.primary), ...marked.filter((f) => !f.primary)];
}

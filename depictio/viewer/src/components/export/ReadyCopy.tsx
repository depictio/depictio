import React from 'react';
import { Badge, Button, Group, Paper, SegmentedControl, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
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
  const rebuilding = status.rebuilding || status.report?.rebuilding;
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

import React, { useEffect, useState } from 'react';
import { Button, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  getPublicBundleStatus,
  publicBundleDownloadUrl,
  type PublicBundleStatus,
  type PublicCopyFile,
} from 'depictio-react-core';
import { formatBundleBytes, formatBuiltAt } from './format';

/**
 * The visitors' ready copies of a public dashboard (#1480): the files the
 * project's owner lets anyone download, already built at the dashboard's
 * default view. Each export format's card offers its own copy beside the
 * export of the current view; these are the pieces it uses.
 */

/** The copies on offer, asked once per dashboard; null when there are none
 *  (either switch off, a private project, the offer off, nothing built yet)
 *  or when `dashboardId` is null (the reader builds exports themselves). */
export function usePublicCopy(dashboardId: string | null): PublicBundleStatus | null {
  const [status, setStatus] = useState<PublicBundleStatus | null>(null);
  useEffect(() => {
    setStatus(null);
    if (!dashboardId) return;
    let alive = true;
    void getPublicBundleStatus(dashboardId).then((s) => {
      if (alive) setStatus(s?.available ? s : null);
    });
    return () => {
      alive = false;
    };
  }, [dashboardId]);
  return status;
}

/** The size of one ready copy, or undefined when it is not on offer. */
export function publicCopySize(
  status: PublicBundleStatus | null,
  file: PublicCopyFile,
): number | null | undefined {
  if (!status) return undefined;
  if (file === 'dashboard') return status.size_bytes;
  const report = status.report;
  if (!report?.available) return undefined;
  if (file === 'report') return report.size_bytes;
  return report.pdf_available ? report.pdf_size_bytes : undefined;
}

/** "Download · 13.4 MB": a plain link, since the route needs no credentials
 *  and answers with a redirect or an attachment. */
export const PublicCopyButton: React.FC<{
  dashboardId: string;
  file: PublicCopyFile;
  sizeBytes?: number | null;
}> = ({ dashboardId, file, sizeBytes }) => {
  const size = formatBundleBytes(sizeBytes);
  return (
    <Button
      component="a"
      href={publicBundleDownloadUrl(dashboardId, file)}
      download
      variant="light"
      size="sm"
      leftSection={<Icon icon="mdi:download" width={16} />}
      data-testid={`public-copy-download-${file}`}
    >
      {size ? `Download · ${size}` : 'Download'}
    </Button>
  );
};

/** Which view the ready copies show and when they were built. */
export function publicCopyNote(status: PublicBundleStatus | null): string | null {
  if (!status) return null;
  const built = formatBuiltAt(status.built_at);
  const parts = [`Download: the default view${built ? `, built ${built}` : ''}`];
  if (status.rebuilding || status.report?.rebuilding) parts.push('a newer copy is being prepared');
  return parts.join(' · ');
}

/** One dimmed line under a card's buttons. */
export const ExportNote: React.FC<{ children: React.ReactNode; testId?: string }> = ({
  children,
  testId,
}) => (
  <Text size="xs" c="dimmed" lh={1.35} data-testid={testId}>
    {children}
  </Text>
);

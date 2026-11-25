import React, { useEffect, useState } from 'react';
import { Button, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  getPublicBundleStatus,
  publicBundleDownloadUrl,
  type PublicBundleStatus,
} from 'depictio-react-core';
import ExportFormatCard from '../../chrome/ExportFormatCard';
import { formatBundleBytes, formatBuiltAt } from './format';

/**
 * A visitor's offline copy of a public dashboard (#1480): the file the
 * project's owner lets anyone download, already built. Asks the server once
 * whether one exists and renders nothing when it does not (either switch
 * off, a private project, the download off, or nothing built yet).
 *
 * Where the instance renders reports, the report + dashboard file and its PDF
 * sit beside it once a worker has rendered them (the dashboard copy first, so
 * the card never waits on a render).
 *
 * Each button is a plain link: the route needs no credentials and answers with
 * a redirect to the file or the file itself, so the browser saves it as is.
 */
const PublicCopyCard: React.FC<{ dashboardId: string }> = ({ dashboardId }) => {
  const [status, setStatus] = useState<PublicBundleStatus | null>(null);

  useEffect(() => {
    let alive = true;
    setStatus(null);
    void getPublicBundleStatus(dashboardId).then((s) => {
      if (alive) setStatus(s);
    });
    return () => {
      alive = false;
    };
  }, [dashboardId]);

  if (!status?.available) return null;
  const built = formatBuiltAt(status.built_at);
  const details = [formatBundleBytes(status.size_bytes), built ? `built ${built}` : null]
    .filter(Boolean)
    .join(' · ');
  const report = status.report;
  const reportReady = Boolean(report?.available);
  return (
    <ExportFormatCard
      icon="mdi:download-box-outline"
      title="Offline copy"
      description={
        <>
          The interactive dashboard as one HTML file that opens without a server or a
          network, at its default view.
          {reportReady &&
            ' The report puts the written report first, with a switch to the same dashboard; the PDF is the report to print.'}
          {details && (
            <Text component="span" size="xs" c="dimmed" display="block" mt={4}>
              {details}
              {status.rebuilding && ' · a newer copy is being prepared'}
            </Text>
          )}
          {report && !reportReady && (
            <Text component="span" size="xs" c="dimmed" display="block" mt={2}>
              The report and its PDF are being prepared.
            </Text>
          )}
        </>
      }
      testId="public-copy-card"
    >
      <Group gap="xs">
        <Button
          component="a"
          href={publicBundleDownloadUrl(dashboardId)}
          download
          size="sm"
          leftSection={<Icon icon="mdi:download" width={16} />}
          data-testid="public-copy-download"
        >
          {reportReady ? 'Dashboard' : 'Download offline copy'}
        </Button>
        {reportReady && (
          <Button
            component="a"
            href={publicBundleDownloadUrl(dashboardId, 'report')}
            download
            size="sm"
            variant="default"
            leftSection={<Icon icon="mdi:file-document-outline" width={16} />}
            title={formatBundleBytes(report?.size_bytes) || undefined}
            data-testid="public-copy-download-report"
          >
            Report + dashboard
          </Button>
        )}
        {reportReady && report?.pdf_available && (
          <Button
            component="a"
            href={publicBundleDownloadUrl(dashboardId, 'pdf')}
            download
            size="sm"
            variant="default"
            leftSection={<Icon icon="mdi:file-pdf-box" width={16} />}
            title={formatBundleBytes(report?.pdf_size_bytes) || undefined}
            data-testid="public-copy-download-pdf"
          >
            PDF
          </Button>
        )}
      </Group>
    </ExportFormatCard>
  );
};

export default PublicCopyCard;

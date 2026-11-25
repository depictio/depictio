import React, { useEffect, useState } from 'react';
import { Button, Text } from '@mantine/core';
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
 * The button is a plain link: the route needs no credentials and answers with
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
  return (
    <ExportFormatCard
      icon="mdi:download-box-outline"
      title="Offline copy"
      description={
        <>
          The interactive dashboard as one HTML file that opens without a server or a
          network, at its default view.
          {details && (
            <Text component="span" size="xs" c="dimmed" display="block" mt={4}>
              {details}
              {status.rebuilding && ' · a newer copy is being prepared'}
            </Text>
          )}
        </>
      }
      testId="public-copy-card"
    >
      <Button
        component="a"
        href={publicBundleDownloadUrl(dashboardId)}
        download
        size="sm"
        leftSection={<Icon icon="mdi:download" width={16} />}
        data-testid="public-copy-download"
      >
        Download offline copy
      </Button>
    </ExportFormatCard>
  );
};

export default PublicCopyCard;

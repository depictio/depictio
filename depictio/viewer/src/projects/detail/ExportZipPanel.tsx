import React, { useState } from 'react';
import { Alert, Button, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { exportProjectZip } from 'depictio-react-core';

import { ErrorAlert } from '../../components/settings/SettingsSections';

interface ExportZipPanelProps {
  projectId: string;
}

/**
 * The Export section of the project settings: the same ZIP bundle the project
 * actions menu downloads, so the two places read alike. It is the counterpart
 * of Import > From a ZIP file on the Projects page.
 */
const ExportZipPanel: React.FC<ExportZipPanelProps> = ({ projectId }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const download = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await exportProjectZip(projectId);
      setDone(true);
    } catch (err) {
      setError((err as Error).message || 'The project could not be exported.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap="lg" data-testid="export-zip-panel">
      <Text size="sm">
        Download this project, its data and its dashboards as one .zip file. To bring it into
        another Depictio instance, use Import &gt; From a ZIP file on the Projects page.
      </Text>
      {error && (
        <ErrorAlert title="The project was not exported" data-testid="export-zip-error">
          {error}
        </ErrorAlert>
      )}
      {done && (
        <Alert
          color="teal"
          variant="light"
          icon={<Icon icon="mdi:check-circle-outline" width={18} />}
          title="Export started"
          data-testid="export-zip-success"
        >
          depictio_export_{projectId}.zip is downloading.
        </Alert>
      )}
      <div>
        <Button
          size="sm"
          loading={busy}
          leftSection={<Icon icon="mdi:export" width={16} />}
          onClick={() => void download()}
          data-testid="export-zip-submit"
        >
          Export as ZIP
        </Button>
      </div>
    </Stack>
  );
};

export default ExportZipPanel;

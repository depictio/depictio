import React, { useRef, useState } from 'react';
import {
  Alert,
  Button,
  FileButton,
  Group,
  Modal,
  Stack,
  Switch,
  Tabs,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { MigrationInvite } from 'depictio-react-core';

import { ReceivePanel } from '../admin/ReceivePanel';

type ImportTab = 'receive' | 'zip';

const ZIP_ACCEPT = '.zip,application/zip,application/x-zip-compressed';

/** A .zip bundle exported from another instance, uploaded from this browser. */
const ZipPanel: React.FC<{
  onClose: () => void;
  onImport: (file: File, overwrite: boolean) => Promise<void>;
}> = ({ onClose, onImport }) => {
  const [file, setFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resetRef = useRef<() => void>(null);

  const submit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      await onImport(file, overwrite);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The project could not be imported.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack gap="md" data-testid="import-zip-panel">
      <Text size="sm">
        Upload a .zip bundle exported from another Depictio instance. The project, its data
        and its dashboards are created here.
      </Text>
      <FileButton resetRef={resetRef} accept={ZIP_ACCEPT} onChange={setFile}>
        {(props) => (
          <UnstyledButton
            {...props}
            data-testid="import-zip-drop"
            style={{
              border: '2px dashed var(--mantine-primary-color-filled)',
              borderRadius: 'var(--mantine-radius-md)',
              background: 'var(--mantine-color-default-hover)',
              padding: 'var(--mantine-spacing-lg)',
              textAlign: 'center',
            }}
          >
            <Stack gap={4} align="center">
              <Icon
                icon="mdi:file-upload-outline"
                width={32}
                color="var(--mantine-primary-color-filled)"
              />
              <Text size="sm" fw={500}>
                {file ? file.name : 'Choose a .zip file'}
              </Text>
              {file && (
                <Text size="xs" c="dimmed">
                  {(file.size / 1024).toFixed(1)} KB
                </Text>
              )}
            </Stack>
          </UnstyledButton>
        )}
      </FileButton>
      <Switch
        label="Replace the project if it already exists"
        checked={overwrite}
        onChange={(e) => setOverwrite(e.currentTarget.checked)}
        data-testid="import-zip-overwrite"
      />
      {error && (
        <Alert color="red" variant="light" data-testid="import-zip-error">
          {error}
        </Alert>
      )}
      <Group justify="flex-end">
        <Button variant="subtle" color="gray" onClick={onClose}>
          Cancel
        </Button>
        <Button
          loading={submitting}
          disabled={!file}
          onClick={() => void submit()}
          leftSection={<Icon icon="mdi:check" width={16} />}
          data-testid="import-zip-submit"
        >
          Import project
        </Button>
      </Group>
    </Stack>
  );
};

export interface ImportProjectModalProps {
  opened: boolean;
  onClose: () => void;
  /** Import a .zip bundle. Omitted: the ZIP tab is not offered. */
  onImport?: (file: File, overwrite: boolean) => Promise<void>;
  /** Offer the "another instance" tab (administrators, where migration is on). */
  canReceive?: boolean;
  /** Called after an invite was created, so a listing behind the dialog refreshes. */
  onInviteCreated?: (invite: MigrationInvite) => void;
}

/**
 * One place to bring a project in: from another Depictio instance (an invite
 * code its owner pastes into Send) or from a .zip bundle. With only one of the
 * two on offer the tab bar is left out.
 */
const ImportProjectModal: React.FC<ImportProjectModalProps> = ({
  opened,
  onClose,
  onImport,
  canReceive = false,
  onInviteCreated,
}) => {
  const tabs: ImportTab[] = [...(canReceive ? (['receive'] as const) : []), ...(onImport ? (['zip'] as const) : [])];
  const [tab, setTab] = useState<ImportTab | null>(null);
  const active = tab && tabs.includes(tab) ? tab : tabs[0];

  const receive = (
    <ReceivePanel onClose={onClose} onCreated={onInviteCreated} />
  );
  const zip = onImport ? <ZipPanel onClose={onClose} onImport={onImport} /> : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Import a project"
      centered
      size="md"
      data-testid="import-project-modal"
    >
      {tabs.length > 1 ? (
        <Tabs value={active} onChange={(v) => setTab(v as ImportTab)}>
          <Tabs.List mb="md">
            <Tabs.Tab
              value="receive"
              leftSection={<Icon icon="mdi:transfer-down" width={16} />}
              data-testid="import-tab-receive"
            >
              From another instance
            </Tabs.Tab>
            <Tabs.Tab
              value="zip"
              leftSection={<Icon icon="mdi:folder-zip-outline" width={16} />}
              data-testid="import-tab-zip"
            >
              From a ZIP file
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="receive">{receive}</Tabs.Panel>
          <Tabs.Panel value="zip">{zip}</Tabs.Panel>
        </Tabs>
      ) : active === 'receive' ? (
        receive
      ) : (
        zip
      )}
    </Modal>
  );
};

export default ImportProjectModal;

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';

interface DeleteDashboardModalProps {
  opened: boolean;
  dashboard: DashboardListEntry | null;
  onClose: () => void;
  onConfirm: (dashboardId: string) => Promise<void>;
}

const DeleteDashboardModal: React.FC<DeleteDashboardModalProps> = ({
  opened,
  dashboard,
  onClose,
  onConfirm,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Reset transient state whenever the modal reopens.
  useEffect(() => {
    if (!opened) return;
    setSubmitting(false);
    setErrorMessage(null);
  }, [opened, dashboard]);

  const handleConfirm = async () => {
    if (!dashboard) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onConfirm(dashboard.dashboard_id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to delete dashboard');
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Delete dashboard"
      size="md"
      centered
      closeOnClickOutside={false}
    >
      <Stack gap="sm">
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert" />}
          title="This cannot be undone."
        >
          Delete &quot;{dashboard?.title || 'this dashboard'}&quot;?
        </Alert>

        <Text size="sm" c="dimmed">
          All child tabs and stored components will also be removed.
        </Text>

        {errorMessage && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
            {errorMessage}
          </Alert>
        )}

        <Group justify="flex-end" gap="xs" mt="sm">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color="red"
            leftSection={<Icon icon="tabler:trash" width={14} />}
            onClick={handleConfirm}
            loading={submitting}
            disabled={!dashboard || submitting}
          >
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DeleteDashboardModal;

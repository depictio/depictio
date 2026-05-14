import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  List,
  Loader,
  Modal,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { cleanExampleProjects, listExampleProjects } from 'depictio-react-core';
import type { ExampleProject } from 'depictio-react-core';

/**
 * Admin > Maintenance tab. Single action today: wipe the seed example projects
 * (iris, penguins, nf-core/ampliseq) and everything attached to them. Server
 * cascades via the same path as the per-project delete endpoint.
 *
 * Safety: requires typing "DELETE" in the confirm modal because this removes
 * three projects at once. Mirrors the single-dashboard delete modal's danger
 * styling, but with stricter confirmation.
 */
const CONFIRM_PHRASE = 'DELETE';

const AdminMaintenancePanel: React.FC = () => {
  const [examples, setExamples] = useState<ExampleProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const rows = await listExampleProjects();
      setExamples(rows);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load example projects');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const openConfirm = () => {
    setConfirmText('');
    setSubmitError(null);
    setConfirmOpen(true);
  };

  const handleConfirm = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await cleanExampleProjects();
      notifications.show({
        color: 'green',
        title: 'Example projects cleaned',
        message: res.deleted.length
          ? `Deleted ${res.deleted.length} project${res.deleted.length === 1 ? '' : 's'}.`
          : 'No example projects were present.',
      });
      setConfirmOpen(false);
      await refresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to clean example projects');
    } finally {
      setSubmitting(false);
    }
  };

  const confirmReady = confirmText.trim() === CONFIRM_PHRASE && !submitting;

  return (
    <Stack gap="lg">
      <Card withBorder radius="md" p="lg">
        <Stack gap="md">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Stack gap={4}>
              <Group gap="xs">
                <Icon icon="mdi:broom" width={20} color="var(--mantine-color-orange-6)" />
                <Title order={5}>Clean example projects</Title>
              </Group>
              <Text size="sm" c="dimmed">
                Removes the seed projects (iris, penguins, nf-core/ampliseq) and
                everything they own: dashboards, workflows, data collections, and
                Delta-table objects in S3.
              </Text>
            </Stack>
            <Button
              color="red"
              variant="filled"
              leftSection={<Icon icon="tabler:trash" width={16} />}
              onClick={openConfirm}
              disabled={loading || examples.length === 0}
            >
              Delete example projects
            </Button>
          </Group>

          {loading ? (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Checking for example projects…
              </Text>
            </Group>
          ) : loadError ? (
            <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
              {loadError}
            </Alert>
          ) : examples.length === 0 ? (
            <Group gap="xs">
              <Icon icon="mdi:check-circle" color="var(--mantine-color-green-6)" width={18} />
              <Text size="sm" c="dimmed">
                No example projects present.
              </Text>
            </Group>
          ) : (
            <Stack gap={4}>
              <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                Currently present
              </Text>
              <Group gap="xs" wrap="wrap">
                {examples.map((p) => (
                  <Badge key={p.id} color="orange" variant="light" size="lg">
                    {p.name || p.id}
                  </Badge>
                ))}
              </Group>
            </Stack>
          )}
        </Stack>
      </Card>

      <Modal
        opened={confirmOpen}
        onClose={() => !submitting && setConfirmOpen(false)}
        title="Delete example projects"
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
            The following projects and all their attached data will be removed:
          </Alert>

          <List size="sm" withPadding spacing={4}>
            {examples.map((p) => (
              <List.Item key={p.id}>
                <Text component="span" fw={600}>
                  {p.name || p.id}
                </Text>
                <Text component="span" c="dimmed" ml={6}>
                  ({p.id})
                </Text>
              </List.Item>
            ))}
          </List>

          <Text size="sm" c="dimmed">
            Cascades: dashboards · workflows · data collections · MultiQC reports ·
            JBrowse sessions · Delta-table S3 objects.
          </Text>

          <TextInput
            label={`Type ${CONFIRM_PHRASE} to confirm`}
            placeholder={CONFIRM_PHRASE}
            value={confirmText}
            onChange={(e) => setConfirmText(e.currentTarget.value)}
            disabled={submitting}
            autoFocus
          />

          {submitError && (
            <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
              {submitError}
            </Alert>
          )}

          <Group justify="flex-end" gap="xs" mt="sm">
            <Button
              variant="subtle"
              onClick={() => setConfirmOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              color="red"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              onClick={handleConfirm}
              loading={submitting}
              disabled={!confirmReady}
            >
              Delete {examples.length} project{examples.length === 1 ? '' : 's'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export default AdminMaintenancePanel;

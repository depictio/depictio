import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry, EditDashboardInput } from 'depictio-react-core';

/** Mantine palette options — empty string = "no override" / inherit. */
const COLOR_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Auto' },
  { value: 'gray', label: 'Gray' },
  { value: 'red', label: 'Red' },
  { value: 'pink', label: 'Pink' },
  { value: 'grape', label: 'Grape' },
  { value: 'violet', label: 'Violet' },
  { value: 'indigo', label: 'Indigo' },
  { value: 'blue', label: 'Blue' },
  { value: 'cyan', label: 'Cyan' },
  { value: 'teal', label: 'Teal' },
  { value: 'green', label: 'Green' },
  { value: 'lime', label: 'Lime' },
  { value: 'yellow', label: 'Yellow' },
  { value: 'orange', label: 'Orange' },
  { value: 'dark', label: 'Dark' },
];

/** Mirrors the backend's accepted `workflow_system` values. */
const WORKFLOW_SYSTEM_OPTIONS: { value: string; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'snakemake', label: 'Snakemake' },
  { value: 'nextflow', label: 'Nextflow' },
  { value: 'galaxy', label: 'Galaxy' },
  { value: 'cwl', label: 'CWL' },
  { value: 'smk_wrapper', label: 'Snakemake wrapper' },
  { value: 'python', label: 'Python' },
];

interface EditDashboardModalProps {
  opened: boolean;
  dashboard: DashboardListEntry | null;
  onClose: () => void;
  onSubmit: (dashboardId: string, input: EditDashboardInput) => Promise<void>;
}

const EditDashboardModal: React.FC<EditDashboardModalProps> = ({
  opened,
  dashboard,
  onClose,
  onSubmit,
}) => {
  const [title, setTitle] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [icon, setIcon] = useState('');
  const [iconColor, setIconColor] = useState('');
  const [workflowSystem, setWorkflowSystem] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Re-sync from the target dashboard whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setErrorMessage(null);
    setSubmitting(false);
    if (dashboard) {
      setTitle(dashboard.title || '');
      setSubtitle((dashboard.subtitle as string) || '');
      setIcon(dashboard.icon || '');
      setIconColor(dashboard.icon_color || '');
      setWorkflowSystem((dashboard.workflow_system as string) || '');
    } else {
      setTitle('');
      setSubtitle('');
      setIcon('');
      setIconColor('');
      setWorkflowSystem('');
    }
  }, [opened, dashboard]);

  const trimmedTitle = title.trim();
  const canSubmit = !!dashboard && trimmedTitle.length > 0 && !submitting;

  const handleSubmit = async () => {
    if (!dashboard || !trimmedTitle) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onSubmit(dashboard.dashboard_id, {
        title: trimmedTitle || undefined,
        subtitle: subtitle,
        icon: icon.trim() || undefined,
        icon_color: iconColor || undefined,
        workflow_system: workflowSystem || undefined,
      });
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to save dashboard');
      setSubmitting(false);
    }
  };

  const previewIcon = icon.trim();
  const previewIsImage =
    !!previewIcon &&
    (/^(\/|https?:\/\/|data:)/.test(previewIcon) ||
      /\.(png|svg|jpe?g|webp)$/i.test(previewIcon));
  const previewColorVar = iconColor
    ? `var(--mantine-color-${iconColor}-6)`
    : 'var(--mantine-color-dimmed)';
  const resolvedImageSrc = previewIsImage
    ? previewIcon.startsWith('/') &&
      typeof window !== 'undefined' &&
      window.location.port === '8122'
      ? `${window.location.protocol}//${window.location.hostname}:5122${previewIcon}`
      : previewIcon
    : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Edit "${dashboard?.title || 'dashboard'}"`}
      size="lg"
      centered
    >
      <Stack gap="sm">
        {errorMessage && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
            {errorMessage}
          </Alert>
        )}

        <TextInput
          label="Title"
          placeholder="My dashboard"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
          required
          data-autofocus
        />

        <Textarea
          label="Subtitle"
          placeholder="Short description shown under the title"
          value={subtitle}
          onChange={(e) => setSubtitle(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={4}
        />

        <Select
          label="Workflow system"
          data={WORKFLOW_SYSTEM_OPTIONS}
          value={workflowSystem || 'none'}
          onChange={(v) => setWorkflowSystem(v ?? '')}
          allowDeselect={false}
        />

        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <TextInput
            label="Icon"
            description="Iconify name, e.g. mdi:view-dashboard"
            placeholder="mdi:view-dashboard"
            value={icon}
            onChange={(e) => setIcon(e.currentTarget.value)}
          />
          <Select
            label="Icon color"
            data={COLOR_OPTIONS}
            value={iconColor}
            onChange={(v) => setIconColor(v ?? '')}
            allowDeselect={false}
          />
        </SimpleGrid>

        <Stack gap={4} align="center" mt="xs">
          <div
            style={{
              width: 64,
              height: 64,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 8,
              border: '1px solid var(--mantine-color-default-border)',
            }}
            aria-label="Icon preview"
          >
            {resolvedImageSrc ? (
              <img
                src={resolvedImageSrc}
                alt="icon preview"
                style={{ width: 48, height: 48, objectFit: 'contain' }}
              />
            ) : previewIcon ? (
              <Icon icon={previewIcon} width={48} color={previewColorVar} />
            ) : (
              <Icon
                icon="mdi:view-dashboard"
                width={48}
                style={{ opacity: 0.3 }}
              />
            )}
          </div>
          <Text size="xs" c="dimmed">
            Preview
          </Text>
        </Stack>

        <Group justify="flex-end" gap="xs" mt="sm">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} loading={submitting} disabled={!canSubmit}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default EditDashboardModal;

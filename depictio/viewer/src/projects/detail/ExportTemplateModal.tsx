import React, { useEffect, useState } from 'react';
import {
  Button,
  Group,
  Modal,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import { exportProjectTemplate, useBrandAccents } from 'depictio-react-core';

/** Mirrors the backend's template_id validation: slash-separated path
 *  segments, each `[A-Za-z0-9][A-Za-z0-9._-]*` (e.g. `my-lab/rnaseq-qc/1`). */
const TEMPLATE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*(\/[A-Za-z0-9][A-Za-z0-9._-]*)*$/;

interface ExportTemplateModalProps {
  projectId: string;
  opened: boolean;
  onClose: () => void;
}

/** Export the current project as a reusable template bundle (.zip). Wraps
 *  POST /projects/{id}/export_template — backend 422 `detail` strings are
 *  meaningful (bad id format, round-trip self-check failure) and are shown
 *  verbatim in the error notification. */
const ExportTemplateModal: React.FC<ExportTemplateModalProps> = ({
  projectId,
  opened,
  onClose,
}) => {
  const accent = useBrandAccents();
  const [templateId, setTemplateId] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [description, setDescription] = useState('');
  const [dataRoot, setDataRoot] = useState('');
  const [idError, setIdError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Reset the form whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setTemplateId('');
    setVersion('1.0.0');
    setDescription('');
    setDataRoot('');
    setIdError(null);
    setSubmitting(false);
  }, [opened]);

  const handleExport = async () => {
    const trimmedId = templateId.trim();
    if (!trimmedId) {
      setIdError('Template ID is required.');
      return;
    }
    if (!TEMPLATE_ID_RE.test(trimmedId)) {
      setIdError(
        'Invalid format — use slash-separated segments of letters, digits, ' +
          'dots, dashes or underscores (each starting with a letter or digit), ' +
          'e.g. my-lab/rnaseq-qc/1.',
      );
      return;
    }
    setIdError(null);
    setSubmitting(true);
    try {
      const blob = await exportProjectTemplate(projectId, {
        template_id: trimmedId,
        description: description.trim() || null,
        version: version.trim() || '1.0.0',
        data_root: dataRoot.trim() || null,
      });
      // Hand the zip to the browser as a normal download.
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      // Mirrors the backend's Content-Disposition filename (slashes → '_').
      a.download = `${trimmedId.replace(/\//g, '_')}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      notifications.show({
        color: 'green',
        title: 'Template exported',
        message:
          'Template bundle downloaded — drop the extracted directory into ' +
          'depictio/projects/ to make it available in the template picker',
        autoClose: 6000,
      });
      onClose();
    } catch (err) {
      // Keep the modal open so the user can fix the inputs and retry.
      notifications.show({
        color: 'red',
        title: 'Failed to export template',
        message: (err as Error).message || 'Failed to export template.',
        autoClose: 8000,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={() => !submitting && onClose()}
      centered
      size="lg"
      closeOnEscape={!submitting}
      title={
        <Group gap="xs">
          <Icon
            icon="mdi:package-variant-closed"
            width={22}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Title order={4}>Export as template</Title>
        </Group>
      }
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Package this project's configuration and dashboards into a reusable
          template bundle (.zip).
        </Text>
        <TextInput
          label="Template ID"
          required
          placeholder="my-lab/rnaseq-qc/1"
          description="Slash-separated path segments (letters, digits, dots, dashes, underscores) identifying the template, e.g. my-lab/rnaseq-qc/1"
          data-testid="export-template-id-input"
          value={templateId}
          onChange={(e) => {
            setTemplateId(e.currentTarget.value);
            if (idError) setIdError(null);
          }}
          error={idError ?? undefined}
          disabled={submitting}
        />
        <TextInput
          label="Version"
          placeholder="1.0.0"
          value={version}
          onChange={(e) => setVersion(e.currentTarget.value)}
          disabled={submitting}
        />
        <Textarea
          label="Description (Optional)"
          placeholder="What this template provides…"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={5}
          disabled={submitting}
        />
        <TextInput
          label="Data root (Optional)"
          placeholder="/data/projects/rnaseq"
          description="Local path prefix to re-parameterize as {DATA_ROOT} in the template — leave empty for manifest-driven projects"
          value={dataRoot}
          onChange={(e) => setDataRoot(e.currentTarget.value)}
          disabled={submitting}
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={accent.secondary}
            data-testid="export-template-submit"
            leftSection={<Icon icon="mdi:package-down" width={16} />}
            onClick={handleExport}
            loading={submitting}
          >
            Export
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default ExportTemplateModal;

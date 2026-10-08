import React, { useState } from 'react';
import { Alert, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import { exportProjectTemplate } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';

/** Mirrors the backend's template_id validation: slash-separated path
 *  segments, each `[A-Za-z0-9][A-Za-z0-9._-]*` (e.g. `my-lab/rnaseq-qc/1`). */
const TEMPLATE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*(\/[A-Za-z0-9][A-Za-z0-9._-]*)*$/;

const EDITORS_ONLY = 'Only project owners and editors can export this project as a template.';

interface ExportTemplatePanelProps {
  projectId: string;
  /** Owners, editors and admins may export (the backend's gate). */
  canMutate: boolean;
}

/**
 * The Export template section of the project settings: package the project
 * as a reusable template bundle (.zip). Wraps POST
 * /projects/{id}/export_template; the backend's 422 `detail` strings are
 * meaningful (bad id format, round-trip self-check failure) and are shown
 * verbatim. The form starts empty each time the section opens.
 */
const ExportTemplatePanel: React.FC<ExportTemplatePanelProps> = ({ projectId, canMutate }) => {
  const [templateId, setTemplateId] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [description, setDescription] = useState('');
  const [dataRoot, setDataRoot] = useState('');
  const [idError, setIdError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<string | null>(null);

  const reason = canMutate ? null : EDITORS_ONLY;
  const locked = submitting || !canMutate;

  const handleExport = async () => {
    const trimmedId = templateId.trim();
    if (!trimmedId) {
      setIdError('Template ID is required.');
      return;
    }
    if (!TEMPLATE_ID_RE.test(trimmedId)) {
      setIdError(
        'Invalid format: use slash-separated segments of letters, digits, ' +
          'dots, dashes or underscores (each starting with a letter or digit), ' +
          'e.g. my-lab/rnaseq-qc/1.',
      );
      return;
    }
    setIdError(null);
    setError(null);
    setDownloaded(null);
    setSubmitting(true);
    try {
      const blob = await exportProjectTemplate(projectId, {
        template_id: trimmedId,
        description: description.trim() || null,
        version: version.trim() || '1.0.0',
        data_root: dataRoot.trim() || null,
      });
      // Mirrors the backend's Content-Disposition filename (slashes to '_').
      const filename = `${trimmedId.replace(/\//g, '_')}.zip`;
      // Hand the zip to the browser as a normal download.
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloaded(filename);
    } catch (err) {
      // The form stays filled so the user can fix the inputs and retry.
      setError((err as Error).message || 'The template could not be exported.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack gap="md" data-testid="export-template-panel">
      <Text size="sm" c="dimmed">
        Package this project&apos;s configuration and dashboards as a template bundle (.zip),
        so the same layout can be built again on other data.
      </Text>
      <TextInput
        label="Template ID"
        required
        placeholder="my-lab/rnaseq-qc/1"
        description="Names the template: slash-separated parts made of letters, digits, dots, dashes or underscores, such as my-lab/rnaseq-qc/1."
        data-testid="export-template-id-input"
        value={templateId}
        onChange={(e) => {
          setTemplateId(e.currentTarget.value);
          if (idError) setIdError(null);
        }}
        error={idError ?? undefined}
        disabled={locked}
      />
      <TextInput
        label="Version"
        description="Recorded in the bundle, so later exports of the same template can be told apart."
        placeholder="1.0.0"
        value={version}
        onChange={(e) => setVersion(e.currentTarget.value)}
        disabled={locked}
      />
      <Textarea
        label="Description (optional)"
        description="Shown next to the template wherever it is offered."
        placeholder="What this template provides..."
        value={description}
        onChange={(e) => setDescription(e.currentTarget.value)}
        autosize
        minRows={2}
        maxRows={5}
        disabled={locked}
      />
      <TextInput
        label="Data root (optional)"
        description="The folder this project's files were read from. It becomes a placeholder in the template, so the template works on another machine. Leave empty for a project read from a manifest or a URL."
        placeholder="/data/projects/rnaseq"
        value={dataRoot}
        onChange={(e) => setDataRoot(e.currentTarget.value)}
        disabled={locked}
      />
      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
          title="The template was not exported"
          data-testid="export-template-error"
        >
          {error}
        </Alert>
      )}
      {downloaded && (
        <Alert
          color="teal"
          variant="light"
          icon={<Icon icon="mdi:check-circle-outline" width={18} />}
          title="Template exported"
          data-testid="export-template-success"
        >
          {downloaded} is downloaded. To offer it in the template picker, unzip it into the
          server&apos;s depictio/projects/ folder.
        </Alert>
      )}
      <Stack gap={6} align="flex-end">
        <GatedButton
          data-testid="export-template-submit"
          leftSection={<Icon icon="mdi:package-down" width={16} />}
          onClick={handleExport}
          loading={submitting}
          reason={reason}
        >
          Export
        </GatedButton>
        <DisabledReason reason={reason} />
      </Stack>
    </Stack>
  );
};

export default ExportTemplatePanel;

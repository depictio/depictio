/**
 * The last part of the review: check the template against the folder (a dry
 * run, shown with the run-folder plan), then act on it.
 *
 * - Server mode: `from_run` with the inline template, dry run first, then
 *   for real; the page then shows `RunCreatedModal`.
 * - Standalone: `/plan`, then `/write` next to the data (an existing bundle
 *   is overwritten only once confirmed), then the `depictio ingest` command.
 *
 * The plan belongs to the template it was made with: once the draft
 * changes, it has to be previewed again before acting.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Code,
  CopyButton,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  apiErrorCode,
  builderPlan,
  builderWrite,
  createProjectFromRun,
  isHttpStatus,
  runFoundNothing,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  BuilderContext,
  BuilderRootSpec,
  BuilderTemplateResult,
  BuilderWriteResult,
  FromRunReport,
} from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { RunPreview } from '../../fromRun/RunPreview';

type PlanState =
  | { status: 'idle' }
  | { status: 'loading'; yaml: string }
  | { status: 'ready'; yaml: string; report: FromRunReport }
  | { status: 'error'; yaml: string; error: string };

/** The plan, its button and what it found. */
const PlanSection: React.FC<{
  plan: PlanState;
  current: boolean;
  disabledReason: string | null;
  onPlan: () => void;
  engine: string | null;
  storage: BuilderRootSpec['storage'];
}> = ({ plan, current, disabledReason, onPlan, engine, storage }) => {
  const accent = useBrandAccents();
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Text fw={600} size="sm">
            Check against the folder
          </Text>
          <Text size="xs" c="dimmed">
            A dry run: what each collection finds, nothing is created or written.
          </Text>
        </Stack>
        <Stack gap={4} align="flex-end">
          <GatedButton
            variant="light"
            color={accent.secondary}
            leftSection={<Icon icon="mdi:magnify-scan" width={16} />}
            onClick={onPlan}
            loading={plan.status === 'loading'}
            reason={disabledReason}
            data-testid="builder-plan"
          >
            {plan.status === 'idle' ? 'Preview the ingestion' : 'Preview again'}
          </GatedButton>
        </Stack>
      </Group>
      {plan.status !== 'idle' && !current && (
        <Alert color="yellow" variant="light" p="xs" icon={<Icon icon="mdi:refresh" width={14} />}>
          <Text size="xs">The draft changed since this preview: preview again before going on.</Text>
        </Alert>
      )}
      {plan.status === 'loading' && (
        <Group gap="xs">
          <Loader size="sm" color={accent.secondary} />
          <Text size="sm" c="dimmed">
            Reading the folder with the template...
          </Text>
        </Group>
      )}
      {plan.status === 'error' && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />} data-testid="builder-plan-error">
          <Text size="sm">{plan.error}</Text>
        </Alert>
      )}
      {plan.status === 'ready' && (
        <Box data-testid="builder-plan-report" style={{ opacity: current ? 1 : 0.6 }}>
          <RunPreview
            report={plan.report}
            templateTitle={null}
            templateEngine={engine}
            detection={null}
            storage={storage ?? null}
          />
        </Box>
      )}
    </Stack>
  );
};

/** Why the plan's outcome stops the last action; null when it does not. */
function planBlocker(plan: PlanState, current: boolean): string | null {
  if (plan.status === 'idle') return 'Preview the ingestion first.';
  if (plan.status === 'loading') return 'Reading the folder.';
  if (plan.status === 'error') return 'The preview failed: fix the draft, then preview again.';
  if (!current) return 'The draft changed: preview the ingestion again.';
  if (runFoundNothing(plan.report.data_collections)) {
    return 'No data collection matched anything in this folder.';
  }
  return null;
}

// ── Server mode ─────────────────────────────────────────────────────────────

export const ServerCreatePanel: React.FC<{
  root: BuilderRootSpec;
  template: BuilderTemplateResult | null;
  /** Why there is no template yet (draft issues, a refusal); null with one. */
  templateBlocker: string | null;
  projectName: string;
  existingNames: string[];
  /** Project creation is not available to this user. */
  createDisabledReason: string | null;
  engine: string | null;
  onCreated: (report: FromRunReport) => void;
}> = ({
  root,
  template,
  templateBlocker,
  projectName,
  existingNames,
  createDisabledReason,
  engine,
  onCreated,
}) => {
  const accent = useBrandAccents();
  const [plan, setPlan] = useState<PlanState>({ status: 'idle' });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const yaml = template?.yaml ?? '';
  const current = plan.status !== 'idle' && plan.yaml === yaml;
  const name = projectName.trim();
  const nameUsed = existingNames.some((n) => n.toLowerCase() === name.toLowerCase());

  const request = (dryRun: boolean) => ({
    dataRoot: root.data_root,
    template: template?.template ?? null,
    projectName: name || null,
    dryRun,
    ...(root.storage ? { storage: root.storage } : {}),
  });

  const runPlan = () => {
    if (!template) return;
    setPlan({ status: 'loading', yaml });
    setError(null);
    createProjectFromRun(request(true))
      .then((report) => setPlan({ status: 'ready', yaml, report }))
      .catch((err: Error) =>
        setPlan({ status: 'error', yaml, error: err.message || 'The folder could not be read.' }),
      );
  };

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      const report = await createProjectFromRun(request(false));
      onCreated(report);
    } catch (err) {
      setError((err as Error).message || 'The project could not be created.');
    } finally {
      setCreating(false);
    }
  };

  const planReason = templateBlocker ?? (nameUsed ? 'A project with this name already exists.' : null);
  const createReason =
    createDisabledReason ?? planReason ?? planBlocker(plan, current);

  return (
    <Paper withBorder radius="md" p="md" data-testid="builder-create-panel">
      <Stack gap="md">
        <PlanSection
          plan={plan}
          current={current}
          disabledReason={planReason}
          onPlan={runPlan}
          engine={engine}
          storage={root.storage}
        />
        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />} data-testid="builder-create-error">
            {error}
          </Alert>
        )}
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Text size="xs" c="dimmed" maw={420}>
            Creating the project ingests every collection in the background; you can watch it
            on the next screen. Dashboards are built afterwards, in the editor.
            {root.storage
              ? " The private bucket's connection details are saved as the project's storage settings."
              : ''}
          </Text>
          <Stack gap={4} align="flex-end">
            <GatedButton
              color={accent.secondary}
              leftSection={<Icon icon="mdi:rocket-launch-outline" width={16} />}
              onClick={create}
              loading={creating}
              reason={createReason}
              data-testid="builder-create"
            >
              Create project
            </GatedButton>
            <DisabledReason reason={createReason} icon="mdi:information-outline" testId="builder-create-reason" />
          </Stack>
        </Group>
      </Stack>
    </Paper>
  );
};

// ── Standalone ──────────────────────────────────────────────────────────────

export const StandaloneCreatePanel: React.FC<{
  context: BuilderContext;
  template: BuilderTemplateResult | null;
  templateBlocker: string | null;
  engine: string | null;
}> = ({ context, template, templateBlocker, engine }) => {
  const accent = useBrandAccents();
  const [plan, setPlan] = useState<PlanState>({ status: 'idle' });
  const [writing, setWriting] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [written, setWritten] = useState<(BuilderWriteResult & { yaml: string }) | null>(null);
  const yaml = template?.yaml ?? '';
  const current = plan.status !== 'idle' && plan.yaml === yaml;

  const runPlan = () => {
    if (!template) return;
    setPlan({ status: 'loading', yaml });
    setError(null);
    builderPlan(template.template)
      .then((report) => setPlan({ status: 'ready', yaml, report }))
      .catch((err: Error) =>
        setPlan({ status: 'error', yaml, error: err.message || 'The folder could not be read.' }),
      );
  };

  const write = async (overwrite: boolean) => {
    if (!template) return;
    setWriting(true);
    setError(null);
    try {
      const result = await builderWrite(template.template, overwrite);
      setWritten({ ...result, yaml });
      setConfirmOverwrite(false);
    } catch (err) {
      if (apiErrorCode(err) === 'bundle_exists' || isHttpStatus(err, 409)) {
        setConfirmOverwrite(true);
      } else {
        setError((err as Error).message || 'The template could not be written.');
      }
    } finally {
      setWriting(false);
    }
  };

  const writeReason =
    templateBlocker ??
    (!context.writable
      ? `${context.out_dir} is not writable: download the template instead.`
      : planBlocker(plan, current));
  const writtenCurrent = written !== null && written.yaml === yaml;

  return (
    <Paper withBorder radius="md" p="md" data-testid="builder-create-panel">
      <Stack gap="md">
        <PlanSection
          plan={plan}
          current={current}
          disabledReason={templateBlocker}
          onPlan={runPlan}
          engine={engine}
          storage={null}
        />
        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />} data-testid="builder-write-error">
            {error}
          </Alert>
        )}
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Text size="xs" c="dimmed" maw={420}>
            Writes the template bundle to{' '}
            <Text span ff="monospace" size="xs">
              {context.out_dir}
            </Text>
            , ready for <Text span ff="monospace" size="xs">depictio ingest</Text>.
          </Text>
          <Stack gap={4} align="flex-end">
            <GatedButton
              color={accent.secondary}
              leftSection={<Icon icon="mdi:content-save-outline" width={16} />}
              onClick={() => write(false)}
              loading={writing && !confirmOverwrite}
              reason={writeReason}
              data-testid="builder-write"
            >
              Write template
            </GatedButton>
            <DisabledReason reason={writeReason} icon="mdi:information-outline" testId="builder-write-reason" />
          </Stack>
        </Group>
        {written && (
          <Alert
            color={writtenCurrent ? accent.secondary : 'yellow'}
            variant="light"
            icon={<Icon icon={writtenCurrent ? 'mdi:check-circle' : 'mdi:alert'} width={18} />}
            title={writtenCurrent ? 'Template written' : 'Written before the latest changes'}
            data-testid="builder-written"
          >
            <Stack gap="xs">
              <Text size="sm">
                <Text span ff="monospace" size="sm" data-testid="builder-written-path">
                  {written.path}
                </Text>
              </Text>
              <Text size="sm">Ingest the folder with it:</Text>
              <Group gap="xs" wrap="nowrap" align="flex-start">
                <Code block style={{ flex: 1, minWidth: 0 }} data-testid="builder-ingest-command">
                  {written.ingest_command}
                </Code>
                <CopyButton value={written.ingest_command} timeout={1500}>
                  {({ copied, copy }) => (
                    <Tooltip label={copied ? 'Copied' : 'Copy the command'} withArrow>
                      <ActionIcon
                        variant="light"
                        color={copied ? accent.secondary : 'gray'}
                        onClick={copy}
                        aria-label="Copy the command"
                        data-testid="builder-ingest-command-copy"
                      >
                        <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </CopyButton>
              </Group>
            </Stack>
          </Alert>
        )}
      </Stack>
      <Modal
        opened={confirmOverwrite}
        onClose={() => !writing && setConfirmOverwrite(false)}
        title="Replace the existing template?"
        centered
      >
        <Stack gap="md" data-testid="builder-overwrite-confirm">
          <Text size="sm">
            A template bundle already exists in{' '}
            <Text span ff="monospace" size="sm">
              {context.out_dir}
            </Text>
            . Writing replaces it.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => setConfirmOverwrite(false)} disabled={writing}>
              Keep it
            </Button>
            <Button
              color="red"
              onClick={() => write(true)}
              loading={writing}
              data-testid="builder-overwrite-confirm-button"
            >
              Replace
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
};

/**
 * The checks of a run folder against the template that reads it, one line
 * each, wherever a run folder is summed up (the folder browser, the detection
 * card, the Preview step):
 *
 *  - Pipeline, Version, Engine: what the run's records say, next to what the
 *    template was written for; one value when both agree, both when not;
 *  - Tasks: how the run's tasks ended, from its execution trace;
 *  - Folder: one run or several, of one pipeline version, listed in full;
 *  - Input files: the files the template is pointed at (samplesheet, ...);
 *  - Collections: what the template finds in the folder, opening onto every
 *    data collection, where it looked and what it found.
 *
 * The last four are read from the dry run of the folder (`useRunPlan`), and
 * wait for it; the run's records read with the folder fill Tasks before.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  formatVersion,
  groupRunCollections,
  runTemplateMatchText,
  sameVersion,
  splitTemplateId,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  FromRunReport,
  RunInfoSummary,
  RunInputFile,
  RunStorageIn,
  RunTaskSummary,
  RunTemplateMatch,
} from 'depictio-react-core';

import { engineLabel, TemplateSourceLogo, WorkflowEngineLogo } from '../template';
import { CollectionPlan } from './CollectionPlan';
import { RunFilePath, RunFileScope } from './FilePreview';
import { FlowBadge, matchStatus } from './FlowBadge';
import { plural } from './plural';
import type { RunPlanState } from './runPlan';

/** What made a run, as far as the server could tell. */
export interface RunInfo {
  pipeline: string | null;
  version: string | null;
  engine: string | null;
}

type CheckStatus = 'ok' | 'differs' | 'warn' | 'fail' | 'info' | 'unknown' | 'loading';

const STATUS: Record<Exclude<CheckStatus, 'loading'>, { icon: string; color: string; label: string }> = {
  ok: { icon: 'mdi:check-circle', color: 'green', label: 'Passes' },
  differs: { icon: 'mdi:approximately-equal', color: 'yellow', label: 'Differs' },
  warn: { icon: 'mdi:alert-circle', color: 'orange', label: 'Needs a look' },
  fail: { icon: 'mdi:close-circle', color: 'red', label: 'Fails' },
  info: { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Optional, absent' },
  unknown: { icon: 'mdi:help-circle-outline', color: 'gray', label: 'Cannot be checked' },
};

/** How the two sides of an identity row agree, as the tests and the mark
 *  read it. */
type Agreement = 'same' | 'differs' | 'conflict' | 'unknown';

const AGREEMENT_STATUS: Record<Agreement, CheckStatus> = {
  same: 'ok',
  differs: 'differs',
  conflict: 'warn',
  unknown: 'unknown',
};

function agreement(
  run: string | null | undefined,
  template: string | null | undefined,
): Agreement {
  if (!run || !template) return 'unknown';
  return run.toLowerCase() === template.toLowerCase() ? 'same' : 'conflict';
}

/** Why a template other than the run's own is used, without repeating the
 *  versions the line already shows. */
const MATCH_REASON: Partial<Record<RunTemplateMatch, string>> = {
  closest: 'No template exists for the run’s version; the closest one is used.',
  'other-version': 'The template you picked was written for another version.',
  'other-pipeline': 'The template you picked was written for another pipeline.',
  none: 'No installed template matches this run. Pick one yourself.',
};

const Mark: React.FC<{
  status: CheckStatus;
  label?: string;
  testId?: string;
  agreementValue?: Agreement;
}> = ({ status, label, testId, agreementValue }) => {
  if (status === 'loading') {
    return <Loader size={14} aria-label="Checking" data-testid={testId} />;
  }
  const meta = STATUS[status];
  return (
    <Tooltip label={label ?? meta.label} withArrow zIndex={Z_LAYERS.tooltip}>
      <ThemeIcon
        variant="transparent"
        color={meta.color}
        size="sm"
        aria-label={label ?? meta.label}
        data-testid={testId}
        data-agreement={agreementValue}
      >
        <Icon icon={meta.icon} width={16} />
      </ThemeIcon>
    </Tooltip>
  );
};

const Dim: React.FC<{ children: React.ReactNode; testId?: string }> = ({ children, testId }) => (
  <Text span size="sm" c="dimmed" data-testid={testId}>
    {children}
  </Text>
);

interface CheckProps {
  check: string;
  label: string;
  status: CheckStatus;
  statusLabel?: string;
  testIdPrefix: string;
  /** For the identity rows: the agreement mark's own test id and value. */
  markTestId?: string;
  agreementValue?: Agreement;
  /** Opened under the line by a click on it. */
  details?: React.ReactNode;
  toggleTestId?: string;
  children: React.ReactNode;
}

const Check: React.FC<CheckProps> = ({
  check,
  label,
  status,
  statusLabel,
  testIdPrefix,
  markTestId,
  agreementValue,
  details,
  toggleTestId,
  children,
}) => {
  const [open, setOpen] = useState(false);
  const toggle = () => setOpen((o) => !o);
  return (
    <>
      <Table.Tr
        data-testid={`${testIdPrefix}-check-${check}`}
        data-status={status}
        onClick={details ? toggle : undefined}
        style={details ? { cursor: 'pointer' } : undefined}
      >
        <Table.Td>
          <Mark status={status} label={statusLabel} testId={markTestId} agreementValue={agreementValue} />
        </Table.Td>
        <Table.Td>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            {label}
          </Text>
        </Table.Td>
        <Table.Td>{children}</Table.Td>
        <Table.Td>
          {details && (
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              onClick={(event) => {
                event.stopPropagation();
                toggle();
              }}
              aria-expanded={open}
              aria-label={open ? `Hide the ${label.toLowerCase()} details` : `Show the ${label.toLowerCase()} details`}
              data-testid={toggleTestId ?? `${testIdPrefix}-check-${check}-toggle`}
            >
              <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={16} />
            </ActionIcon>
          )}
        </Table.Td>
      </Table.Tr>
      {details && open && (
        <Table.Tr data-testid={`${testIdPrefix}-check-${check}-details`}>
          <Table.Td />
          <Table.Td colSpan={3} pb="sm">
            {details}
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
};

const n = (value: number) => value.toLocaleString();

function tasksCheck(tasks: RunTaskSummary | null | undefined): { status: CheckStatus; text: string } {
  if (!tasks) {
    return { status: 'unknown', text: 'No execution trace in pipeline_info, so not checked' };
  }
  const done = tasks.completed + tasks.cached;
  const cut = tasks.partial ? ' (start of the trace only)' : '';
  if (tasks.failed > 0) {
    return { status: 'warn', text: `${n(tasks.failed)} failed, ${n(done)} completed${cut}` };
  }
  if (tasks.other > 0) {
    return { status: 'warn', text: `${n(tasks.other)} not finished, ${n(done)} completed${cut}` };
  }
  const extras = [
    tasks.cached > 0 ? `${n(tasks.cached)} from cache` : null,
    tasks.retried > 0 ? `${n(tasks.retried)} after a retry` : null,
  ].filter(Boolean);
  return {
    status: 'ok',
    text: `${plural(done, 'task')} completed${extras.length ? ` (${extras.join(', ')})` : ''}, none failed${cut}`,
  };
}

function folderCheck(
  runInfo: RunInfoSummary | null,
  report: FromRunReport | null,
  listingCut: boolean,
): { status: CheckStatus; text: string } {
  const parts: string[] = [];
  let status: CheckStatus = 'ok';
  const identities = runInfo?.identities_seen ?? [];
  if (identities.length > 1) {
    status = 'warn';
    parts.push(`Runs of more than one pipeline or version: ${identities.join(', ')}`);
  }
  const runs = report?.detected_runs.length || runInfo?.runs_scanned || 0;
  if (runs > 1 || (report?.detected_runs.length ?? 0) > 0) {
    parts.push(`${plural(runs, 'run')}, read together`);
  }
  if (listingCut || report?.truncated) {
    status = 'warn';
    parts.push('the listing stopped early, so every count is a minimum');
  }
  if (parts.length === 0) return { status, text: 'One run, listed in full' };
  const text = parts.join(' · ');
  return { status, text: text.charAt(0).toUpperCase() + text.slice(1) };
}

const baseName = (location: string) => location.replace(/\/+$/, '').split('/').pop() || location;

function inputsCheck(files: RunInputFile[]): { status: CheckStatus; text: string } {
  const missing = files.filter((f) => f.required && f.found !== true);
  const absent = files.filter((f) => !f.required && (f.location === null || f.found === false));
  const found = files.filter((f) => f.location && f.found === true);
  const parts: string[] = [];
  if (found.length > 0) parts.push(found.map((f) => baseName(f.location as string)).join(', '));
  if (missing.length > 0) parts.push(`${missing.map((f) => f.name).join(', ')} not found`);
  if (absent.length > 0) parts.push(`${absent.map((f) => f.name).join(', ')} not set`);
  let status: CheckStatus = 'ok';
  if (missing.length > 0) status = 'fail';
  else if (absent.length > 0) status = 'info';
  else if (files.some((f) => f.location && f.found === null)) status = 'unknown';
  return { status, text: parts.join(' · ') };
}

function collectionsCheck(report: FromRunReport): { status: CheckStatus; text: string } {
  const groups = groupRunCollections(report.data_collections);
  const ready = groups.ready.length;
  const missing = groups.missing.length;
  const optional = groups.optional.length;
  if (ready + missing + optional === 0) {
    return { status: 'unknown', text: 'The template looks for no collection here' };
  }
  const parts = [`${ready} found`];
  if (missing > 0) parts.push(`${missing} not found`);
  if (optional > 0) parts.push(`${optional} optional absent`);
  let status: CheckStatus = 'ok';
  if (missing > 0) status = ready === 0 ? 'fail' : 'warn';
  return { status, text: parts.join(' · ') };
}

const InputFiles: React.FC<{ files: RunInputFile[] }> = ({ files }) => (
  <Stack gap={6} data-testid="run-input-files">
    {files.map((file) => {
      let status: CheckStatus = 'unknown';
      if (file.found === true) status = 'ok';
      else if (file.required) status = 'fail';
      else if (file.location === null || file.found === false) status = 'info';
      return (
        <Group key={file.name} gap={6} wrap="nowrap" align="flex-start" data-input={file.name}>
          <Mark status={status} label={file.found ? 'Found' : file.location ? 'Not found' : 'Not set'} />
          <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
            <Group gap={6} wrap="wrap">
              <Code fz="xs">{file.name}</Code>
              {file.required && (
                <Text span size="xs" c="dimmed" fs="italic">
                  required
                </Text>
              )}
              {file.used_by.length > 0 && (
                <Text span size="xs" c="dimmed">
                  used by {file.used_by.join(', ')}
                </Text>
              )}
            </Group>
            {file.location ? (
              file.found ? (
                <RunFilePath location={file.location} />
              ) : (
                <Text size="xs" ff="monospace" c="red" style={{ wordBreak: 'break-all' }}>
                  {file.location}
                </Text>
              )
            ) : (
              <Text size="xs" c="dimmed">
                {file.description || 'Not set for this run.'}
              </Text>
            )}
          </Stack>
        </Group>
      );
    })}
  </Stack>
);

interface RunChecksProps {
  /** The folder checked: a real path or an `s3://` URL. */
  location: string;
  run: RunInfo | null;
  /** The template the project uses (chosen, else detected); null when none. */
  templateId: string | null;
  /** The template's name; the id is shown when it is not known. */
  templateName: string | null;
  /** The engine the template was written for, when the catalog says. */
  templateEngine?: string | null;
  match: RunTemplateMatch | null;
  /** The dry run of the folder with the template; null without a template. */
  plan: RunPlanState | null;
  /** The run's records as read with the folder, before the plan answers. */
  runInfo?: RunInfoSummary | null;
  /** The folder's own listing was cut short. */
  listingCut?: boolean;
  /** The private bucket's connection details, to preview its files. */
  storage?: RunStorageIn | null;
  /** False where the full plan is shown below the checks anyway. */
  withPlan?: boolean;
  testIdPrefix: string;
}

export const RunChecks: React.FC<RunChecksProps> = ({
  location,
  run,
  templateId,
  templateName,
  templateEngine = null,
  match,
  plan,
  runInfo = null,
  listingCut = false,
  storage = null,
  withPlan = true,
  testIdPrefix: p,
}) => {
  const parts = templateId ? splitTemplateId(templateId) : null;
  const templatePipeline = parts?.pipeline ?? null;
  const templateVersion = parts?.version ?? null;
  const report = plan?.status === 'ready' ? plan.report : null;
  const records = report?.run_info ?? runInfo;
  const planPending = plan?.status === 'loading';

  const pipelineAgreement = agreement(run?.pipeline, templatePipeline);
  let versionAgreement: Agreement = 'unknown';
  if (run?.version && templateVersion) {
    versionAgreement = sameVersion(run.version, templateVersion) ? 'same' : 'differs';
  }
  const engineAgreement = agreement(run?.engine, templateEngine);
  const matchText = match
    ? runTemplateMatchText(match, { run: run?.version, template: templateVersion })
    : null;
  const reason = match ? MATCH_REASON[match] : undefined;

  const tasks = records
    ? tasksCheck(records.tasks)
    : planPending
      ? null
      : tasksCheck(null);
  const folder = planPending ? null : folderCheck(records, report, listingCut);
  const inputFiles = report?.input_files ?? [];
  const inputs = report && inputFiles.length > 0 ? inputsCheck(inputFiles) : null;
  const collections = report ? collectionsCheck(report) : null;
  const runs = report?.detected_runs ?? [];

  return (
    <RunFileScope dataRoot={report?.data_root ?? location} storage={storage}>
      <Stack gap={4} data-testid={`${p}-comparison`}>
        <Group justify="space-between" wrap="nowrap" gap="sm">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            Checks
          </Text>
          {match && matchText && (
            <FlowBadge
              status={matchStatus(match)}
              label={matchText.label}
              tooltip={matchText.detail}
              testId={`${p}-match`}
              dataAttributes={{ 'data-match': match }}
            />
          )}
        </Group>
        <Table.ScrollContainer minWidth={420} type="native">
          <Table layout="fixed" verticalSpacing={5} horizontalSpacing={6} highlightOnHover>
            <colgroup>
              <col style={{ width: 30 }} />
              <col style={{ width: 104 }} />
              <col />
              <col style={{ width: 36 }} />
            </colgroup>
            <Table.Tbody>
              <Check
                check="pipeline"
                label="Pipeline"
                status={AGREEMENT_STATUS[pipelineAgreement]}
                testIdPrefix={p}
                markTestId={`${p}-pipeline-agreement`}
                agreementValue={pipelineAgreement}
              >
                <Group gap={6} wrap="wrap" style={{ minWidth: 0 }}>
                  {run?.pipeline ? (
                    <Group gap={6} wrap="nowrap">
                      <TemplateSourceLogo source={splitTemplateId(run.pipeline).source} size={16} />
                      <Text span size="sm" fw={600} data-testid={`${p}-pipeline`}>
                        {run.pipeline}
                      </Text>
                    </Group>
                  ) : (
                    <Dim testId={`${p}-pipeline`}>Not recognised</Dim>
                  )}
                  {templateId ? (
                    <Dim>
                      {pipelineAgreement === 'conflict' ? `template ${templatePipeline}: ` : 'read with '}
                      <Text
                        span
                        size="sm"
                        c="dimmed"
                        fw={500}
                        data-testid={`${p}-template`}
                        data-template-id={templateId}
                      >
                        {templateName || templateId}
                      </Text>
                    </Dim>
                  ) : (
                    <Dim testId={`${p}-template`}>no template chosen yet</Dim>
                  )}
                </Group>
              </Check>

              <Check
                check="version"
                label="Version"
                status={AGREEMENT_STATUS[versionAgreement]}
                testIdPrefix={p}
                markTestId={`${p}-version-agreement`}
                agreementValue={versionAgreement}
              >
                <Stack gap={0}>
                  <Group gap={6} wrap="wrap">
                    {versionAgreement === 'same' ? (
                      <>
                        <Text span size="sm" ff="monospace" data-testid={`${p}-version`}>
                          {formatVersion(run?.version as string)}
                        </Text>
                        <Dim>the version the template was written for</Dim>
                      </>
                    ) : (
                      <>
                        <Dim>run</Dim>
                        <Text span size="sm" ff="monospace" data-testid={`${p}-version`}>
                          {run?.version ? formatVersion(run.version) : 'unknown'}
                        </Text>
                        {templateId && (
                          <>
                            <Dim>· template</Dim>
                            <Text span size="sm" ff="monospace" data-testid={`${p}-template-version`}>
                              {templateVersion ? formatVersion(templateVersion) : 'single version'}
                            </Text>
                          </>
                        )}
                      </>
                    )}
                  </Group>
                  {versionAgreement !== 'same' && reason && (
                    <Text size="xs" c="dimmed" data-testid={`${p}-match-detail`}>
                      {reason}
                    </Text>
                  )}
                </Stack>
              </Check>

              <Check
                check="engine"
                label="Engine"
                status={AGREEMENT_STATUS[engineAgreement]}
                statusLabel={engineAgreement === 'unknown' ? 'The template does not say' : undefined}
                testIdPrefix={p}
                markTestId={`${p}-engine-agreement`}
                agreementValue={engineAgreement}
              >
                <Group gap={6} wrap="wrap">
                  {run?.engine ? (
                    <Group gap={6} wrap="nowrap">
                      <WorkflowEngineLogo engine={run.engine} size={16} />
                      <Text span size="sm" data-testid={`${p}-engine`}>
                        {engineLabel(run.engine)}
                        {records?.engine_version ? ` ${records.engine_version}` : ''}
                      </Text>
                    </Group>
                  ) : (
                    <Dim testId={`${p}-engine`}>not stated</Dim>
                  )}
                  {templateEngine && engineAgreement !== 'same' && (
                    <Dim>
                      · template written for{' '}
                      <Text span size="sm" c="dimmed" data-testid={`${p}-template-engine`}>
                        {engineLabel(templateEngine)}
                      </Text>
                    </Dim>
                  )}
                </Group>
              </Check>

              {(records || plan) && (
                <Check
                  check="tasks"
                  label="Tasks"
                  status={tasks?.status ?? 'loading'}
                  testIdPrefix={p}
                  details={
                    records?.tasks ? (
                      <Stack gap={2}>
                        <Text size="xs" c="dimmed">
                          The execution trace the engine wrote, one row per task attempt.
                        </Text>
                        <RunFilePath location={records.tasks.trace} />
                      </Stack>
                    ) : undefined
                  }
                >
                  <Text size="sm">{tasks?.text ?? 'Reading the run...'}</Text>
                </Check>
              )}

              {(records || plan) && (
                <Check
                  check="folder"
                  label="Folder"
                  status={folder?.status ?? 'loading'}
                  testIdPrefix={p}
                  details={
                    runs.length > 0 ? (
                      <Group gap={6} wrap="wrap" data-testid={`${p}-detected-runs`}>
                        {runs.map((name) => (
                          <Code key={name}>{name}</Code>
                        ))}
                      </Group>
                    ) : undefined
                  }
                >
                  <Text size="sm">{folder?.text ?? 'Reading the folder...'}</Text>
                </Check>
              )}

              {plan && (planPending || inputs) && (
                <Check
                  check="inputs"
                  label="Input files"
                  status={inputs?.status ?? 'loading'}
                  testIdPrefix={p}
                  details={inputs ? <InputFiles files={inputFiles} /> : undefined}
                >
                  <Text size="sm" style={{ wordBreak: 'break-word' }}>
                    {inputs?.text ?? 'Looking for them...'}
                  </Text>
                </Check>
              )}

              {plan && (
                <Check
                  check="collections"
                  label="Collections"
                  status={collections?.status ?? (plan.status === 'error' ? 'unknown' : 'loading')}
                  testIdPrefix={p}
                  toggleTestId={`${p}-findings-toggle`}
                  details={
                    withPlan && report && report.data_collections.length > 0 ? (
                      <CollectionPlan
                        rows={report.data_collections}
                        dataRoot={report.data_root}
                        storage={storage}
                      />
                    ) : undefined
                  }
                >
                  {plan.status === 'error' ? (
                    <Text size="sm" c="dimmed" data-testid={`${p}-findings-error`}>
                      Not checked: {plan.error}
                    </Text>
                  ) : (
                    <Text size="sm" data-testid={`${p}-findings-summary`}>
                      {collections?.text ?? 'Previewing the folder with the template...'}
                    </Text>
                  )}
                </Check>
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Stack>
    </RunFileScope>
  );
};

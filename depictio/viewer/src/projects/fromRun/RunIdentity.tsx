/**
 * The run next to the template that reads it, as one comparison table,
 * wherever a run folder is summed up (the detection card, the folder
 * browser, the preview header):
 *
 *  - "This run": what the pipeline wrote in its own records (the pipeline,
 *    the version OF THE RUN, the engine);
 *  - "Depictio template": the template Depictio reads the run with, and the
 *    pipeline version and engine it was written for.
 *
 * One row per property, each with a mark saying whether the two sides agree,
 * then the verdict in words. Both versions are spelled out on purpose: the
 * run's version and the template's are different things that often carry
 * the same number.
 */
import React from 'react';
import { Group, Stack, Table, Text, ThemeIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  formatVersion,
  runTemplateMatchText,
  sameVersion,
  splitTemplateId,
  Z_LAYERS,
} from 'depictio-react-core';
import type { RunTemplateMatch } from 'depictio-react-core';

import { engineLabel, TemplateSourceLogo, WorkflowEngineLogo } from '../template';
import { FlowBadge, matchStatus } from './FlowBadge';

/** What made a run, as far as the server could tell. */
export interface RunInfo {
  pipeline: string | null;
  version: string | null;
  engine: string | null;
}

type Agreement = 'same' | 'differs' | 'conflict' | 'unknown';

const AGREEMENT: Record<Agreement, { icon: string; color: string; label: string }> = {
  same: { icon: 'mdi:check-circle', color: 'green', label: 'Same on both sides' },
  differs: { icon: 'mdi:approximately-equal', color: 'yellow', label: 'Differs' },
  conflict: { icon: 'mdi:close-circle', color: 'orange', label: 'Does not match' },
  unknown: { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Cannot be compared' },
};

const AgreementMark: React.FC<{ agreement: Agreement; testId: string }> = ({ agreement, testId }) => {
  const meta = AGREEMENT[agreement];
  return (
    <Tooltip label={meta.label} withArrow zIndex={Z_LAYERS.tooltip}>
      <ThemeIcon
        variant="transparent"
        color={meta.color}
        size="sm"
        aria-label={meta.label}
        data-testid={testId}
        data-agreement={agreement}
      >
        <Icon icon={meta.icon} width={16} />
      </ThemeIcon>
    </Tooltip>
  );
};

function agreement(run: string | null | undefined, template: string | null | undefined, conflict: Agreement): Agreement {
  if (!run || !template) return 'unknown';
  return run.toLowerCase() === template.toLowerCase() ? 'same' : conflict;
}

const Missing: React.FC<{ children: React.ReactNode; testId?: string }> = ({ children, testId }) => (
  <Text size="sm" c="dimmed" fs="italic" data-testid={testId}>
    {children}
  </Text>
);

const EngineCell: React.FC<{ engine: string | null | undefined; testId: string }> = ({ engine, testId }) =>
  engine ? (
    <Group gap={6} wrap="nowrap">
      <WorkflowEngineLogo engine={engine} size={16} />
      <Text size="sm" data-testid={testId}>
        {engineLabel(engine)}
      </Text>
    </Group>
  ) : (
    <Missing testId={testId}>not stated</Missing>
  );

const ColumnHead: React.FC<{ icon: string; title: string; caption: string }> = ({
  icon,
  title,
  caption,
}) => (
  <Stack gap={0}>
    <Group gap={6} wrap="nowrap">
      <Icon icon={icon} width={16} />
      <Text size="sm" fw={700}>
        {title}
      </Text>
    </Group>
    <Text size="xs" c="dimmed" fw={400}>
      {caption}
    </Text>
  </Stack>
);

interface RunTemplateTableProps {
  run: RunInfo | null;
  /** The template the project uses (chosen, else detected); null when none. */
  templateId: string | null;
  /** The template's name; the id is shown when it is not known. */
  templateName: string | null;
  /** The engine the template was written for, when the catalog says. */
  templateEngine?: string | null;
  match: RunTemplateMatch | null;
  testIdPrefix: string;
  /** Heading of the template column, e.g. "Template used" once created. */
  templateHeading?: string;
  /** Under the verdict: what the template finds in the folder, for instance. */
  footer?: React.ReactNode;
}

export const RunTemplateTable: React.FC<RunTemplateTableProps> = ({
  run,
  templateId,
  templateName,
  templateEngine = null,
  match,
  testIdPrefix,
  templateHeading = 'Depictio template',
  footer,
}) => {
  const parts = templateId ? splitTemplateId(templateId) : null;
  const templatePipeline = parts?.pipeline ?? null;
  const templateVersion = parts?.version ?? null;
  const text = match ? runTemplateMatchText(match, { run: run?.version, template: templateVersion }) : null;

  let versionAgreement: Agreement = 'unknown';
  if (run?.version && templateVersion) {
    versionAgreement = sameVersion(run.version, templateVersion) ? 'same' : 'differs';
  }
  const pipelineAgreement = agreement(run?.pipeline, templatePipeline, 'conflict');
  const p = testIdPrefix;

  return (
    <Stack gap="xs" data-testid={`${p}-comparison`}>
      <Table.ScrollContainer minWidth={420} type="native">
        <Table
          layout="fixed"
          verticalSpacing={6}
          horizontalSpacing="sm"
          withTableBorder
          withColumnBorders
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={92} />
              <Table.Th>
                <ColumnHead
                  icon="mdi:folder-play-outline"
                  title="This run"
                  caption="What the pipeline wrote in its records"
                />
              </Table.Th>
              <Table.Th>
                <ColumnHead
                  icon="mdi:view-dashboard-outline"
                  title={templateHeading}
                  caption="How Depictio reads the run into dashboards"
                />
              </Table.Th>
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Pipeline
                </Text>
              </Table.Td>
              <Table.Td>
                {run?.pipeline ? (
                  <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                    <TemplateSourceLogo source={splitTemplateId(run.pipeline).source} size={18} />
                    <Text size="sm" fw={600} style={{ wordBreak: 'break-word' }} data-testid={`${p}-pipeline`}>
                      {run.pipeline}
                    </Text>
                  </Group>
                ) : (
                  <Missing testId={`${p}-pipeline`}>Not recognised</Missing>
                )}
              </Table.Td>
              <Table.Td>
                {templateId && parts ? (
                  <Group gap={6} wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
                    <TemplateSourceLogo source={parts.source} size={18} />
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" fw={600} style={{ wordBreak: 'break-word' }}>
                        {templatePipeline}
                      </Text>
                      <Text
                        size="xs"
                        c="dimmed"
                        style={{ wordBreak: 'break-word' }}
                        data-testid={`${p}-template`}
                        data-template-id={templateId}
                      >
                        {templateName || templateId}
                      </Text>
                    </Stack>
                  </Group>
                ) : (
                  <Missing testId={`${p}-template`}>Not chosen yet</Missing>
                )}
              </Table.Td>
              <Table.Td>
                <AgreementMark agreement={pipelineAgreement} testId={`${p}-pipeline-agreement`} />
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Version
                </Text>
              </Table.Td>
              <Table.Td>
                {run?.pipeline ? (
                  <Text size="sm" ff="monospace" data-testid={`${p}-version`}>
                    {run.version ? formatVersion(run.version) : 'unknown'}
                  </Text>
                ) : (
                  <Missing>unknown</Missing>
                )}
              </Table.Td>
              <Table.Td>
                {templateId ? (
                  <Text size="sm" ff="monospace" data-testid={`${p}-template-version`}>
                    {templateVersion ? formatVersion(templateVersion) : 'single version'}
                  </Text>
                ) : (
                  <Missing>none</Missing>
                )}
              </Table.Td>
              <Table.Td>
                <AgreementMark agreement={versionAgreement} testId={`${p}-version-agreement`} />
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                  Engine
                </Text>
              </Table.Td>
              <Table.Td>
                {run?.pipeline ? (
                  <EngineCell engine={run.engine} testId={`${p}-engine`} />
                ) : (
                  <Missing>unknown</Missing>
                )}
              </Table.Td>
              <Table.Td>
                {templateId ? (
                  <EngineCell engine={templateEngine} testId={`${p}-template-engine`} />
                ) : (
                  <Missing>none</Missing>
                )}
              </Table.Td>
              <Table.Td>
                <AgreementMark
                  agreement={agreement(run?.engine, templateEngine, 'conflict')}
                  testId={`${p}-engine-agreement`}
                />
              </Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      {match && text && (
        <Group gap="sm" wrap="nowrap" align="flex-start" data-testid={`${p}-verdict`}>
          <FlowBadge
            status={matchStatus(match)}
            label={text.label}
            testId={`${p}-match`}
            dataAttributes={{ 'data-match': match }}
          />
          {templateId && (
            <Text size="xs" c="dimmed" data-testid={`${p}-match-detail`}>
              {text.detail}
            </Text>
          )}
        </Group>
      )}
      {footer}
    </Stack>
  );
};

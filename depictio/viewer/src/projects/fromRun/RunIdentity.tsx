/**
 * The two halves of every run-folder summary, side by side wherever they
 * appear (the detection card, the folder browser, the preview header):
 *
 *  - "Run made by": the pipeline and the version OF THE RUN, and its engine;
 *  - "Template Depictio uses": the template and the pipeline version it was
 *    written for, with how well that matches the run.
 *
 * Spelling both versions out, each with its own caption, is the point: the
 * run's version and the template's version are different things that often
 * carry the same number.
 */
import React from 'react';
import { Group, Stack, Text } from '@mantine/core';

import { formatVersion, runTemplateMatchText, splitTemplateId } from 'depictio-react-core';
import type { RunTemplateMatch } from 'depictio-react-core';

import { engineLabel, TemplateSourceLogo, WorkflowEngineLogo } from '../template';
import { FlowBadge, matchStatus } from './FlowBadge';

/** What made a run, as far as the server could tell. */
export interface RunInfo {
  pipeline: string | null;
  version: string | null;
  engine: string | null;
}

const Heading: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" fw={700} c="dimmed" tt="uppercase">
    {children}
  </Text>
);

export const RunMadeBy: React.FC<{ run: RunInfo | null; testIdPrefix: string }> = ({
  run,
  testIdPrefix,
}) => (
  <Stack gap={6} style={{ minWidth: 0 }}>
    <Heading>Run made by</Heading>
    {run?.pipeline ? (
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <TemplateSourceLogo source={splitTemplateId(run.pipeline).source} size={28} />
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} style={{ wordBreak: 'break-word' }} data-testid={`${testIdPrefix}-pipeline`}>
            {run.pipeline}
          </Text>
          <Group gap={8} wrap="wrap">
            <Text size="sm" ff="monospace" data-testid={`${testIdPrefix}-version`}>
              {run.version ? formatVersion(run.version) : 'version unknown'}
            </Text>
            {run.engine && (
              <Group gap={4} wrap="nowrap">
                <WorkflowEngineLogo engine={run.engine} size={14} />
                <Text size="xs" c="dimmed" data-testid={`${testIdPrefix}-engine`}>
                  {engineLabel(run.engine)}
                </Text>
              </Group>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            Pipeline version of the run
          </Text>
        </Stack>
      </Group>
    ) : (
      <Text size="sm" c="dimmed" data-testid={`${testIdPrefix}-pipeline`}>
        Not recognised
      </Text>
    )}
  </Stack>
);

export const TemplateUsed: React.FC<{
  templateId: string | null;
  /** The template's name; the id when the catalog does not list it. */
  title: string | null;
  match: RunTemplateMatch | null;
  runVersion: string | null;
  testIdPrefix: string;
  /** Heading override, e.g. "Template used" once the choice is final. */
  heading?: string;
}> = ({ templateId, title, match, runVersion, testIdPrefix, heading }) => {
  const version = templateId ? splitTemplateId(templateId).version : null;
  const text = match ? runTemplateMatchText(match, { run: runVersion, template: version }) : null;
  return (
    <Stack gap={6} style={{ minWidth: 0 }}>
      <Heading>{heading ?? 'Template Depictio uses'}</Heading>
      {templateId ? (
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <TemplateSourceLogo source={splitTemplateId(templateId).source} size={28} />
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text
              size="sm"
              fw={600}
              style={{ wordBreak: 'break-word' }}
              data-testid={`${testIdPrefix}-template`}
              data-template-id={templateId}
            >
              {title || templateId}
            </Text>
            <Group gap={8} wrap="wrap">
              <Text size="sm" ff="monospace" data-testid={`${testIdPrefix}-template-version`}>
                {version ? formatVersion(version) : 'single version'}
              </Text>
              {match && text && (
                <FlowBadge
                  status={matchStatus(match)}
                  label={text.label}
                  tooltip={text.detail}
                  testId={`${testIdPrefix}-match`}
                  dataAttributes={{ 'data-match': match }}
                />
              )}
            </Group>
            <Text size="xs" c="dimmed">
              Template version: the pipeline version it was written for
            </Text>
          </Stack>
        </Group>
      ) : (
        <Stack gap={4}>
          {match && text ? (
            <Group gap={8} wrap="wrap">
              <FlowBadge
                status={matchStatus(match)}
                label={text.label}
                testId={`${testIdPrefix}-match`}
                dataAttributes={{ 'data-match': match }}
              />
            </Group>
          ) : (
            <Text size="sm" c="dimmed" data-testid={`${testIdPrefix}-template`}>
              Not chosen yet
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
};

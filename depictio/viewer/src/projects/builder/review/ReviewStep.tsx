/**
 * The "Review & create" step: the project and its workflows at a glance,
 * what still needs fixing, the links between collections, the generated
 * template (copy, download), and the create panel of the mode.
 */
import React from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  CopyButton,
  Grid,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderAction, BuilderIssue, BuilderRootSpec, BuilderState } from 'depictio-react-core';

import { useBuilderCapabilities } from '../BuilderCapabilitiesContext';
import { useBuilderMode } from '../BuilderModeContext';
import { DcCard } from '../collections/DcCard';
import { templateFileName } from '../paths';
import { engineLabel, WorkflowLogo } from '../workflows/WorkflowLogo';
import { LinksSection } from './LinksSection';
import type { TemplateState } from './useBuilderTemplate';
import { YamlBlock } from './YamlBlock';

/** Download the template as a YAML file. */
function downloadYaml(yaml: string, fileName: string): void {
  const blob = new Blob([yaml], { type: 'text/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** The project is realtime and the server can honour it. */
function isRealtime(state: BuilderState, eventsEnabled: boolean | null): boolean {
  return state.project.realtime && eventsEnabled !== false;
}

const IssueList: React.FC<{ issues: BuilderIssue[]; onEditDc: (tag: string) => void }> = ({
  issues,
  onEditDc,
}) => {
  const accent = useBrandAccents();
  if (issues.length === 0) return null;
  const errors = issues.filter((i) => i.level === 'error');
  return (
    <Alert
      color={errors.length ? 'red' : 'yellow'}
      variant="light"
      icon={<Icon icon={errors.length ? 'mdi:alert-circle-outline' : 'mdi:alert-outline'} width={18} />}
      title={errors.length ? 'To fix before creating' : 'Worth a look'}
      data-testid="builder-issues"
    >
      <Stack gap={4}>
        {issues.map((issue, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <Group key={`${issue.code}-${i}`} gap={6} wrap="nowrap" align="flex-start" data-code={issue.code}>
            <Icon
              icon={issue.level === 'error' ? 'mdi:close-circle-outline' : 'mdi:information-outline'}
              width={14}
              style={{ flexShrink: 0, marginTop: 3 }}
            />
            <Text size="sm">{issue.message}</Text>
            {issue.tag && (
              <Button color={accent.secondary} size="compact-xs" variant="subtle" onClick={() => onEditDc(issue.tag as string)}>
                Edit
              </Button>
            )}
          </Group>
        ))}
      </Stack>
    </Alert>
  );
};

interface ReviewStepProps {
  state: BuilderState;
  dispatch: React.Dispatch<BuilderAction>;
  root: BuilderRootSpec;
  dataRoot: string;
  remote: boolean;
  issues: BuilderIssue[];
  template: TemplateState;
  onEditProject: () => void;
  onEditDc: (tag: string) => void;
  /** The mode's create panel. */
  createPanel: React.ReactNode;
}

export const ReviewStep: React.FC<ReviewStepProps> = ({
  state,
  dispatch,
  root,
  dataRoot,
  remote,
  issues,
  template,
  onEditProject,
  onEditDc,
  createPanel,
}) => {
  const accent = useBrandAccents();
  const mode = useBuilderMode();
  const { capabilities } = useBuilderCapabilities();
  const realtime = isRealtime(state, capabilities.realtime.events_enabled);
  const { project } = state;
  const result = template.status === 'ready' ? template.result : null;
  const count = state.workflows.reduce((n, w) => n + w.data_collections.length, 0);

  return (
    <Grid gutter="md" p="md" data-testid="builder-review">
      <Grid.Col span={{ base: 12, lg: 7 }}>
        <Stack gap="md">
          <Paper withBorder radius="md" p="md">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Stack gap={4} style={{ minWidth: 0 }}>
                <Group gap="xs">
                  <Text fw={700} size="lg" data-testid="builder-review-project-name">
                    {project.name.trim() || '(no name yet)'}
                  </Text>
                  {project.is_public && (
                    <Badge size="sm" variant="light" color={accent.secondary}>
                      public
                    </Badge>
                  )}
                  {realtime && (
                    <Badge size="sm" variant="light" color="grape">
                      realtime
                    </Badge>
                  )}
                </Group>
                {project.description.trim() && (
                  <Text size="sm" c="dimmed">
                    {project.description.trim()}
                  </Text>
                )}
                {project.data_management_platform_project_url.trim() && (
                  <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all' }}>
                    <Icon icon="mdi:link-variant" width={12} style={{ verticalAlign: 'middle' }} />{' '}
                    {project.data_management_platform_project_url.trim()}
                  </Text>
                )}
                <Text size="xs" c="dimmed" ff="monospace" style={{ wordBreak: 'break-all' }}>
                  {dataRoot}
                </Text>
              </Stack>
              <Button
                color={accent.secondary}
                variant="subtle"
                size="compact-sm"
                leftSection={<Icon icon="mdi:pencil-outline" width={14} />}
                onClick={onEditProject}
              >
                Edit
              </Button>
            </Group>
          </Paper>

          <IssueList issues={issues} onEditDc={onEditDc} />

          <Text size="sm" fw={600}>
            {state.workflows.length} workflow{state.workflows.length === 1 ? '' : 's'} · {count} data
            collection{count === 1 ? '' : 's'}
          </Text>
          {state.workflows.map((w) => (
            <Paper key={w.id} withBorder radius="md" p="sm" data-testid="builder-review-workflow" data-workflow={w.name}>
              <Group gap="xs" mb={6}>
                <WorkflowLogo engine={w.engine} catalog={w.catalog?.name} size={16} />
                <Text size="sm" fw={600}>
                  {w.name || '(unnamed)'}
                </Text>
                <Badge size="xs" variant="light" color="gray" tt="none">
                  {engineLabel(w.engine)}
                </Badge>
                <Badge size="xs" variant="light" tt="none">
                  {w.structure === 'sequencing-runs' ? `runs: ${w.runs_regex ?? ''}` : 'flat'}
                </Badge>
              </Group>
              {w.data_collections.length ? (
                <Stack gap={6}>
                  {w.data_collections.map((dc) => (
                    <DcCard key={dc.tag} dc={dc} files={state.claimed[dc.tag]} onEdit={() => onEditDc(dc.tag)} />
                  ))}
                </Stack>
              ) : (
                <Text size="xs" c="dimmed">
                  No data collection.
                </Text>
              )}
            </Paper>
          ))}

          <LinksSection
            state={state}
            dispatch={dispatch}
            root={root}
            remote={remote}
            capabilities={capabilities}
          />

          <Group gap="xs" mt="xs">
            <Icon
              icon={mode === 'standalone' ? 'mdi:content-save-outline' : 'mdi:rocket-launch-outline'}
              width={18}
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Text fw={600}>{mode === 'standalone' ? 'Write the template' : 'Create the project'}</Text>
          </Group>
          {createPanel}
        </Stack>
      </Grid.Col>

      <Grid.Col span={{ base: 12, lg: 5 }}>
        <Paper withBorder radius="md" p="sm" style={{ position: 'sticky', top: 0 }}>
          <Stack gap="xs">
            <Group justify="space-between" wrap="nowrap">
              <Group gap={6} wrap="nowrap">
                <Icon icon="mdi:file-code-outline" width={16} color={`var(--mantine-color-${accent.secondary}-6)`} />
                <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                  Template
                </Text>
                {result && (
                  <Text size="xs" c="dimmed" ff="monospace">
                    {result.template_id}
                  </Text>
                )}
                {template.status === 'loading' && <Loader size={12} />}
              </Group>
              <Group gap={4} wrap="nowrap">
                <CopyButton value={result?.yaml ?? ''} timeout={1500}>
                  {({ copied, copy }) => (
                    <Tooltip label={copied ? 'Copied' : 'Copy the YAML'} withArrow>
                      <ActionIcon
                        variant="default"
                        onClick={copy}
                        disabled={!result}
                        aria-label="Copy the YAML"
                        data-testid="builder-copy-template"
                      >
                        <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={15} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </CopyButton>
                <Button
                  size="compact-sm"
                  variant="light"
                  color={accent.secondary}
                  leftSection={<Icon icon="mdi:download" width={15} />}
                  disabled={!result}
                  onClick={() => result && downloadYaml(result.yaml, templateFileName(result.template_id))}
                  data-testid="builder-download-template"
                >
                  Download template
                </Button>
              </Group>
            </Group>
            {template.status === 'idle' && (
              <Text size="sm" c="dimmed">
                The template shows here once the draft has no errors left.
              </Text>
            )}
            {template.status === 'error' && (
              <Alert
                color="red"
                variant="light"
                icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
                title={template.code === 'inline_template_invalid' ? 'The server refused the draft' : undefined}
                data-testid="builder-template-error"
              >
                <Text size="sm">{template.error}</Text>
              </Alert>
            )}
            {result && result.warnings.length > 0 && (
              <Alert color="yellow" variant="light" p="xs" icon={<Icon icon="mdi:alert-outline" width={14} />}>
                <Stack gap={2}>
                  {result.warnings.map((w) => (
                    <Text key={w} size="xs">
                      {w}
                    </Text>
                  ))}
                </Stack>
              </Alert>
            )}
            {result && (
              <ScrollArea.Autosize mah="70vh" type="auto">
                <YamlBlock code={result.yaml} testId="builder-review-yaml" />
              </ScrollArea.Autosize>
            )}
            {realtime && (
              <Text size="xs" c="dimmed" data-testid="builder-review-realtime-hint">
                {remote ? (
                  <>
                    No watcher for S3: re-ingest with Data refresh or a scheduled{' '}
                    <Text span ff="monospace" size="xs">
                      depictio ingest
                    </Text>
                    .
                  </>
                ) : (
                  <>
                    Dashboards update when the data is ingested again:{' '}
                    <Text span ff="monospace" size="xs">
                      depictio watch
                    </Text>{' '}
                    on the folder,{' '}
                    <Text span ff="monospace" size="xs">
                      depictio ingest
                    </Text>
                    , or the project&apos;s Data refresh.
                  </>
                )}
              </Text>
            )}
          </Stack>
        </Paper>
      </Grid.Col>
    </Grid>
  );
};

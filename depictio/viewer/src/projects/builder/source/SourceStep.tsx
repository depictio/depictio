/**
 * The "Source & project" step: where the files are (picked in server mode,
 * fixed in standalone mode), and the project's name, description,
 * visibility and realtime switch.
 */
import React from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderAction, BuilderProjectFields } from 'depictio-react-core';

import { plural } from '../../fromRun/plural';
import type { RootProbe, ServerRoot } from './useServerRoot';
import type { StandaloneRoot } from './useStandaloneRoot';

const SectionTitle: React.FC<{ icon: string; children: React.ReactNode }> = ({ icon, children }) => {
  const accent = useBrandAccents();
  return (
    <Group gap="xs">
      <Icon icon={icon} width={18} color={`var(--mantine-color-${accent.secondary}-6)`} />
      <Text fw={600}>{children}</Text>
    </Group>
  );
};

/** What reading the root's top level found. */
const ProbeLine: React.FC<{ probe: RootProbe; current: string; hint: string | null }> = ({
  probe,
  current,
  hint,
}) => {
  const accent = useBrandAccents();
  if (probe.status === 'idle' || !current) return null;
  if (probe.status === 'loading' || probe.location !== current) {
    return (
      <Group gap="xs" data-testid="builder-root-status" data-state="loading">
        <Loader size="xs" color={accent.secondary} />
        <Text size="sm" c="dimmed">
          Reading the folder...
        </Text>
      </Group>
    );
  }
  if (probe.status === 'error') {
    return (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:folder-alert-outline" width={16} />}
        data-testid="builder-root-status"
        data-state="error"
      >
        <Stack gap={4}>
          <Text size="sm">{probe.error}</Text>
          {hint && (
            <Text size="sm" c="dimmed">
              {hint}
            </Text>
          )}
        </Stack>
      </Alert>
    );
  }
  const folders = probe.listing.entries.filter((e) => e.is_dir).length;
  const files = probe.listing.entries.length - folders;
  return (
    <Group gap="xs" data-testid="builder-root-status" data-state="ready">
      <Icon icon="mdi:check-circle" width={16} color={`var(--mantine-color-${accent.secondary}-6)`} />
      <Text size="sm">
        {probe.listing.root_label || current}: {plural(folders, 'folder')}, {plural(files, 'file')} at the top
        {probe.listing.truncated ? ' (and more)' : ''}.
      </Text>
    </Group>
  );
};

interface SourceStepProps {
  server: ServerRoot | null;
  standalone: StandaloneRoot | null;
  localDataRootsEnabled: boolean;
  project: BuilderProjectFields;
  dispatch: React.Dispatch<BuilderAction>;
  remote: boolean;
  /** Names of the projects that exist (server mode). */
  existingNames: string[];
}

export const SourceStep: React.FC<SourceStepProps> = ({
  server,
  standalone,
  localDataRootsEnabled,
  project,
  dispatch,
  remote,
  existingNames,
}) => {
  const accent = useBrandAccents();
  const name = project.name.trim();
  const nameUsed = name.length > 0 && existingNames.some((n) => n.toLowerCase() === name.toLowerCase());
  const patch = (p: Partial<BuilderProjectFields>) => dispatch({ type: 'project/patch', patch: p });

  return (
    <Stack gap="md" p="md" maw={820} mx="auto" data-testid="builder-source-step">
      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <SectionTitle icon="mdi:folder-search-outline">Where the files are</SectionTitle>
          {server && (
            <>
              <TextInput
                label="Data root"
                description={
                  localDataRootsEnabled
                    ? 'A folder on this server (a full path, or one starting with ~/) or an s3:// location.'
                    : 'The s3:// location holding the data.'
                }
                required
                placeholder={localDataRootsEnabled ? '~/results/survey' : 's3://bucket/results/survey/'}
                value={server.value}
                onChange={(e) => server.setValue(e.currentTarget.value)}
                leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                error={server.inputError}
                spellCheck={false}
                inputContainer={(input) =>
                  server.browseEnabled ? (
                    <Group gap="xs" wrap="nowrap" align="flex-start">
                      <Box style={{ flex: 1, minWidth: 0 }}>{input}</Box>
                      <Button
                        variant="default"
                        leftSection={<Icon icon="mdi:folder-open-outline" width={16} />}
                        onClick={server.openBrowser}
                        data-testid="builder-root-browse"
                      >
                        Browse
                      </Button>
                    </Group>
                  ) : (
                    input
                  )
                }
                data-testid="builder-root-input"
              />
              {server.privateBucket}
              <ProbeLine probe={server.probe} current={server.trimmed} hint={server.refusalHint} />
            </>
          )}
          {standalone && (
            <>
              {standalone.status === 'loading' && (
                <Group gap="xs">
                  <Loader size="xs" color={accent.secondary} />
                  <Text size="sm" c="dimmed">
                    Asking the builder server which folder it serves...
                  </Text>
                </Group>
              )}
              {standalone.status === 'error' && (
                <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
                  <Stack gap="xs" align="flex-start">
                    <Text size="sm">{standalone.error}</Text>
                    <Button size="xs" variant="light" color="red" onClick={standalone.retry}>
                      Try again
                    </Button>
                  </Stack>
                </Alert>
              )}
              {standalone.status === 'ready' && (
                <Stack gap={6}>
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    <Text size="xs" fw={700} c="dimmed" tt="uppercase" w={96} pt={4} style={{ flexShrink: 0 }}>
                      Data root
                    </Text>
                    <Code style={{ wordBreak: 'break-all' }} data-testid="builder-root-fixed">
                      {standalone.context.data_root}
                    </Code>
                  </Group>
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    <Text size="xs" fw={700} c="dimmed" tt="uppercase" w={96} pt={4} style={{ flexShrink: 0 }}>
                      Writes to
                    </Text>
                    <Code style={{ wordBreak: 'break-all' }}>{standalone.context.out_dir}</Code>
                    <Badge
                      size="sm"
                      variant="light"
                      color={standalone.context.writable ? accent.secondary : 'yellow'}
                      style={{ flexShrink: 0 }}
                    >
                      {standalone.context.writable ? 'writable' : 'read-only'}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed">
                    The folder this builder was started on. To use another one, start{' '}
                    <Text span ff="monospace" size="xs">
                      depictio project-builder &lt;dir&gt;
                    </Text>{' '}
                    on it.
                  </Text>
                </Stack>
              )}
            </>
          )}
        </Stack>
      </Paper>

      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <SectionTitle icon="mdi:folder-star-outline">Project</SectionTitle>
          <TextInput
            label="Project name"
            description="Give the project a descriptive name"
            required
            placeholder="e.g. Coastal survey 2024"
            value={project.name}
            onChange={(e) => patch({ name: e.currentTarget.value })}
            leftSection={<Icon icon="mdi:folder-outline" width={16} />}
            error={nameUsed ? 'A project with this name already exists.' : undefined}
            data-testid="builder-project-name"
          />
          <Textarea
            label="Description"
            placeholder="Optional: what this project is about"
            value={project.description}
            onChange={(e) => patch({ description: e.currentTarget.value })}
            autosize
            minRows={2}
            maxRows={5}
            data-testid="builder-project-description"
          />
          <Switch
            label="Public project"
            description="Visible to every user of the instance"
            checked={project.is_public}
            onChange={(e) => patch({ is_public: e.currentTarget.checked })}
            color={accent.secondary}
            data-testid="builder-project-public"
          />
          <Switch
            label="Realtime"
            description={
              remote
                ? 'Dashboards follow new data as it arrives. On an S3 root this needs `depictio watch` or re-ingestion.'
                : 'Dashboards follow new data as files change in the folder.'
            }
            checked={project.realtime}
            onChange={(e) => patch({ realtime: e.currentTarget.checked })}
            color={accent.secondary}
            data-testid="builder-project-realtime"
          />
        </Stack>
      </Paper>
    </Stack>
  );
};

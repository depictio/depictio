/**
 * The "Source & project" step: where the files are (picked in server mode,
 * fixed in standalone mode), and the project's name, description, data
 * management platform page, visibility and realtime switch.
 *
 * Realtime only does something on a server with real-time events on
 * (`DEPICTIO_EVENTS_ENABLED`, off by default), and only once dashboards
 * exist: they update when data is ingested again (`depictio watch` on a
 * local folder, `depictio ingest`, or the project's Data refresh). Nothing
 * watches an S3 prefix.
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
import { useBuilderCapabilities } from '../BuilderCapabilitiesContext';
import { useBuilderMode } from '../BuilderModeContext';
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
  /** What Depictio recognised in the folder, and the template it offers
   *  (server mode). */
  templateStart?: React.ReactNode;
}

export const REALTIME_EVENTS_OFF_REASON =
  'Real-time events are off on this server (DEPICTIO_EVENTS_ENABLED)';
const REALTIME_STANDALONE_WARNING = 'Takes effect only on a server with real-time events on';
const REALTIME_DESCRIPTION =
  'Live-update dashboards when new data is ingested (depictio watch, depictio ingest or Data refresh).';
const REALTIME_S3_NOTE = 'No watcher for S3: re-ingest with Data refresh or a scheduled depictio ingest.';

/** The realtime switch, gated on whether the server has real-time events. */
const RealtimeSwitch: React.FC<{
  checked: boolean;
  remote: boolean;
  onChange: (checked: boolean) => void;
}> = ({ checked, remote, onChange }) => {
  const accent = useBrandAccents();
  const mode = useBuilderMode();
  const { capabilities } = useBuilderCapabilities();
  const eventsEnabled = capabilities.realtime.events_enabled;
  const off = mode === 'server' && eventsEnabled === false;
  return (
    <Stack gap={4}>
      <Switch
        label="Realtime"
        description={
          <>
            {REALTIME_DESCRIPTION}
            {remote && (
              <>
                <br />
                {REALTIME_S3_NOTE}
              </>
            )}
          </>
        }
        checked={checked && !off}
        disabled={off}
        onChange={(e) => onChange(e.currentTarget.checked)}
        color={accent.secondary}
        data-testid="builder-project-realtime"
      />
      {off && (
        <Group gap={6} wrap="nowrap" pl={54} data-testid="builder-project-realtime-reason">
          <Icon icon="mdi:lock-outline" width={14} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed">
            {REALTIME_EVENTS_OFF_REASON}
          </Text>
        </Group>
      )}
      {mode === 'standalone' && (
        <Group gap={6} wrap="nowrap" pl={54} data-testid="builder-project-realtime-warning">
          <Icon icon="mdi:alert-outline" width={14} color="var(--mantine-color-yellow-6)" style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed">
            {REALTIME_STANDALONE_WARNING}
          </Text>
        </Group>
      )}
    </Stack>
  );
};

export const SourceStep: React.FC<SourceStepProps> = ({
  server,
  standalone,
  localDataRootsEnabled,
  project,
  dispatch,
  remote,
  existingNames,
  templateStart = null,
}) => {
  const accent = useBrandAccents();
  const name = project.name.trim();
  const nameUsed = name.length > 0 && existingNames.some((n) => n.toLowerCase() === name.toLowerCase());
  const dmpUrl = project.data_management_platform_project_url.trim();
  const dmpInvalid = dmpUrl.length > 0 && !/^https?:\/\//.test(dmpUrl);
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

      {templateStart}

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
          <TextInput
            label="Data management platform URL"
            description="Optional: the project's page on a data management platform"
            placeholder="https://"
            value={project.data_management_platform_project_url}
            onChange={(e) => patch({ data_management_platform_project_url: e.currentTarget.value })}
            leftSection={<Icon icon="mdi:link-variant" width={16} />}
            error={dmpInvalid ? 'Starts with http:// or https://' : undefined}
            spellCheck={false}
            data-testid="builder-project-dmp-url"
          />
          <Switch
            label="Public project"
            description="Visible to every user of the instance"
            checked={project.is_public}
            onChange={(e) => patch({ is_public: e.currentTarget.checked })}
            color={accent.secondary}
            data-testid="builder-project-public"
          />
          <RealtimeSwitch
            checked={project.realtime}
            remote={remote}
            onChange={(realtime) => patch({ realtime })}
          />
        </Stack>
      </Paper>
    </Stack>
  );
};

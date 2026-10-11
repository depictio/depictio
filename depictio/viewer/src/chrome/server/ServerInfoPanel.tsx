import React from 'react';
import { Alert, Anchor, Box, Button, Divider, Group, Paper, Stack, Text } from '@mantine/core';
import { BookOpen, Bug, ExternalLink, GitBranch, Tag, type LucideIcon } from 'lucide-react';

import { useCurrentUser } from '../../hooks/useCurrentUser';
import { useServerInfo } from '../../hooks/useServerInfo';
import { useServerStatus } from '../../hooks/useServerStatus';
import { useUpdateNotice } from '../../hooks/useUpdateNotice';
import { formatDate, formatRelativeTime } from '../../lib/datetime';

/**
 * What the reader may want to know about the server they are talking to:
 * whether it is up, which version, where the docs and the releases live, and
 * for an admin whether a newer release is out.
 *
 * One panel, two homes: the popover behind every server status element
 * (`variant="popover"`), and a section of the Account settings page
 * (`variant="section"`, which only adds the frame a card needs). The admin
 * block shows only when the server sent `version_check`, which it does for
 * admins alone, so no role check lives here.
 */

export interface ServerInfoPanelProps {
  variant?: 'popover' | 'section';
}

const EXTERNAL = { target: '_blank', rel: 'noopener noreferrer' } as const;

/** The admin tab that holds the version check switch. */
const ADMIN_SETTINGS_HREF = '/admin/settings';

const DOT_COLOR = { online: 'green.6', offline: 'red.6', unknown: 'gray.5' } as const;

const Dot: React.FC<{ state: keyof typeof DOT_COLOR }> = ({ state }) => (
  <Box
    w={8}
    h={8}
    bg={DOT_COLOR[state]}
    style={{ borderRadius: '50%', flex: 'none' }}
    aria-hidden
  />
);

const Row: React.FC<{ label: string; children: React.ReactNode; testId?: string }> = ({
  label,
  children,
  testId,
}) => (
  <Group justify="space-between" gap="md" wrap="nowrap" data-testid={testId}>
    <Text size="sm" c="dimmed">
      {label}
    </Text>
    <Text size="sm" ta="right" style={{ minWidth: 0 }}>
      {children}
    </Text>
  </Group>
);

const LinkRow: React.FC<{ icon: LucideIcon; href: string; children: string }> = ({
  icon: I,
  href,
  children,
}) => (
  <Anchor href={href} size="sm" {...EXTERNAL}>
    <Group gap={8} wrap="nowrap">
      <I size={15} strokeWidth={1.8} aria-hidden />
      <span>{children}</span>
      <ExternalLink size={12} strokeWidth={1.8} aria-hidden style={{ opacity: 0.6 }} />
    </Group>
  </Anchor>
);

const UpdateBlock: React.FC = () => {
  const { info } = useServerInfo();
  const notice = useUpdateNotice();
  const check = info?.version_check;
  if (!info || !check) return null;

  const releaseHref = notice.releaseUrl ?? info.release_notes_url;
  const notes = (
    <Anchor href={releaseHref} size="sm" {...EXTERNAL}>
      Release notes
    </Anchor>
  );

  if (!check.enabled) {
    return (
      <Stack gap={2} data-testid="server-info-check-off">
        <Text size="sm">Version check is off</Text>
        {check.locked_by_env ? (
          <Text size="xs" c="dimmed">
            (set by DEPICTIO_VERSION_CHECK_ENABLED)
          </Text>
        ) : (
          <Anchor href={ADMIN_SETTINGS_HREF} size="sm">
            Turn it on in Administration
          </Anchor>
        )}
      </Stack>
    );
  }

  if (notice.available && notice.latestVersion) {
    if (!notice.show) {
      return (
        <Group gap={6} data-testid="server-info-update-quiet">
          <Text size="sm">v{notice.latestVersion} available</Text>
          {notes}
        </Group>
      );
    }
    return (
      <Alert
        color="blue"
        variant="light"
        radius="md"
        p="sm"
        title={`Depictio v${notice.latestVersion} is available`}
        data-testid="server-info-update"
      >
        <Stack gap={8}>
          {notice.publishedAt && (
            <Text size="xs" c="dimmed">
              Published {formatDate(notice.publishedAt, '')}
            </Text>
          )}
          <Group justify="space-between" gap="sm">
            {notes}
            <Button
              size="compact-sm"
              variant="light"
              onClick={notice.acknowledge}
              data-testid="server-info-update-ack"
            >
              OK
            </Button>
          </Group>
        </Stack>
      </Alert>
    );
  }

  if (check.last_error && !check.latest_version) {
    return (
      <Text size="sm" data-testid="server-info-check-error">
        Could not reach GitHub
        {check.checked_at ? ` (last attempt ${formatRelativeTime(check.checked_at, 'recently')})` : ''}
      </Text>
    );
  }

  return (
    <Text size="sm" data-testid="server-info-up-to-date">
      {check.checked_at
        ? `Up to date, checked ${formatRelativeTime(check.checked_at, 'recently')}`
        : 'Up to date'}
    </Text>
  );
};

/** Every flag reads false until the auth status arrives, so a mode computed
 *  before then would say "Standard" on a single-user or public instance. */
function modeLabel(flags: {
  isDemoMode: boolean;
  isPublicMode: boolean;
  isSingleUserMode: boolean;
  loading: boolean;
}): string {
  if (flags.loading) return '-';
  if (flags.isDemoMode) return 'Demo';
  if (flags.isPublicMode) return 'Public';
  if (flags.isSingleUserMode) return 'Single user';
  return 'Standard';
}

const ServerInfoPanel: React.FC<ServerInfoPanelProps> = ({ variant = 'popover' }) => {
  const { info, loading } = useServerInfo();
  const { status, version: polledVersion } = useServerStatus();
  const { isPublicMode, isDemoMode, isSingleUserMode, loading: userLoading } = useCurrentUser();

  const mode = modeLabel({ isDemoMode, isPublicMode, isSingleUserMode, loading: userLoading });
  const version = info?.version ?? polledVersion;
  const statusText = status === 'online' ? 'Online' : status === 'unknown' ? 'Checking' : 'Offline';
  const repo = info?.repository_url.replace(/\/+$/, '') ?? null;

  const body = (
    <Stack gap="sm" data-testid="server-info-panel">
      <Group gap={8} wrap="nowrap">
        <Dot state={status} />
        <Text size="sm" fw={600}>
          Depictio server
        </Text>
        <Text size="sm" c="dimmed" ml="auto" data-testid="server-info-status">
          {statusText}
        </Text>
      </Group>

      <Stack gap={4}>
        <Row label="Server version" testId="server-info-version">
          {version ? (
            info ? (
              <Anchor href={info.release_notes_url} size="sm" {...EXTERNAL}>
                v{version}
              </Anchor>
            ) : (
              `v${version}`
            )
          ) : (
            '-'
          )}
        </Row>
        <Row label="API">{info?.api_version ?? '-'}</Row>
        <Row label="Mode">{mode}</Row>
      </Stack>

      {info && repo ? (
        <>
          <Divider />
          <Stack gap={6}>
            <LinkRow icon={BookOpen} href={info.docs_url}>
              Documentation
            </LinkRow>
            <LinkRow icon={GitBranch} href={repo}>
              GitHub
            </LinkRow>
            <LinkRow icon={Tag} href={`${repo}/releases`}>
              Releases
            </LinkRow>
            <LinkRow icon={Bug} href={`${repo}/issues/new/choose`}>
              Report an issue
            </LinkRow>
          </Stack>
        </>
      ) : (
        !loading && (
          <Text size="xs" c="dimmed">
            Links and release details are unavailable right now.
          </Text>
        )
      )}

      {info?.version_check && (
        <>
          <Divider />
          <UpdateBlock />
        </>
      )}
    </Stack>
  );

  return variant === 'section' ? (
    <Paper withBorder radius="md" p="md">
      {body}
    </Paper>
  ) : (
    body
  );
};

export default ServerInfoPanel;

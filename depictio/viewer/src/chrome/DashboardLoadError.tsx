import React from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Code,
  Collapse,
  CopyButton,
  Group,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { classifyLoadError } from 'depictio-react-core';
import type { LoadErrorInfo, LoadErrorKind } from 'depictio-react-core';

import { SIGN_IN_PATH, rememberHere } from '../auth/guestSignIn';
import BrandMark from './BrandMark';
import ProfileBadge from './ProfileBadge';
import ThemeToggle from './ThemeToggle';
import { GlassPage, useGlassPages } from './variants/glass/pages';

/**
 * What the reader sees when a dashboard cannot be loaded: not found, not
 * allowed, or the server is down. One component for the viewer, the editor and
 * the component builder, so the three say the same thing the same way.
 *
 * `DashboardLoadError` is the whole page (the active chrome style's page shell
 * around the card, with no filter panel or dashboard title, since there is no
 * dashboard to name). `DashboardLoadErrorCard` is the card alone, for a page
 * that already has its own shell (the component builder).
 */

/** What failed to load. A single resource (a dashboard, a project) can be
 *  missing; a list (projects, dashboards) cannot, it can only fail. */
export type LoadErrorSubject = 'dashboard' | 'project' | 'projects' | 'dashboards';

interface SubjectInfo {
  /** Singular noun for a single resource, plural for a list. */
  noun: string;
  single: boolean;
  /** The way out, for a single resource. A list page is already where the
   *  reader would go back to, so it only offers "Try again". */
  back: { href: string; label: string; icon: string } | null;
  /** The sidebar section the full-page shell highlights. */
  section: 'dashboards' | 'projects';
}

const SUBJECTS: Record<LoadErrorSubject, SubjectInfo> = {
  dashboard: {
    noun: 'dashboard',
    single: true,
    back: { href: '/dashboards', label: 'Back to dashboards', icon: 'mdi:view-dashboard-outline' },
    section: 'dashboards',
  },
  project: {
    noun: 'project',
    single: true,
    back: { href: '/projects', label: 'Back to projects', icon: 'mdi:folder-outline' },
    section: 'projects',
  },
  projects: { noun: 'projects', single: false, back: null, section: 'projects' },
  dashboards: { noun: 'dashboards', single: false, back: null, section: 'dashboards' },
};

interface KindCopy {
  title: string;
  icon: string;
  color: string;
  text: string;
}

function copyFor(subject: SubjectInfo, info: LoadErrorInfo): KindCopy {
  const { noun, single } = subject;
  const serverText =
    info.status === null
      ? 'The server could not be reached. Check your connection and try again.'
      : `The server answered with an error (${info.status}). This is usually temporary, so try again in a moment.`;
  // A list has no "not found": a 404 there is the server failing, not a
  // missing page, so it reads as unavailable.
  if (info.kind === 'not-found' && single) {
    return {
      title: `${noun[0].toUpperCase()}${noun.slice(1)} not found`,
      icon: 'mdi:file-question-outline',
      color: 'gray',
      text: 'It may have been deleted, or the link may be wrong.',
    };
  }
  if (info.kind === 'forbidden') {
    return {
      title: single ? `You do not have access to this ${noun}` : `You do not have access to the ${noun}`,
      icon: 'mdi:lock-outline',
      color: 'yellow',
      text:
        info.status === 401
          ? 'Your session may have expired. Sign in again, or with another account, to open it.'
          : single
            ? 'It may be private to its owner or to a group you are not in. If you have another account, sign in with it.'
            : 'Your account may not be allowed to list them. If you have another account, sign in with it.',
    };
  }
  return {
    title: `Could not load the ${noun}`,
    icon: 'mdi:cloud-off-outline',
    color: 'red',
    text: serverText,
  };
}

export interface DashboardLoadErrorProps {
  /** What the load threw (an `HttpError` with a `status`, or a network error). */
  error: unknown;
  /** What was being loaded. Defaults to a dashboard. */
  subject?: LoadErrorSubject;
  /** The id from the URL, shown so it can be copied into a bug report or a
   *  message to the owner. Null when the URL carried none. */
  resourceId?: string | null;
  /** Runs the load again. Offered only when asking again can help. */
  onRetry?: () => void;
}

export const LoadErrorCard: React.FC<DashboardLoadErrorProps> = ({
  error,
  subject: subjectKey = 'dashboard',
  resourceId = null,
  onRetry,
}) => {
  const info = React.useMemo(() => classifyLoadError(error), [error]);
  const subject = SUBJECTS[subjectKey];
  const copy = copyFor(subject, info);
  const idLabel = `${subject.noun} id`;
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const actionsRef = React.useRef<HTMLDivElement>(null);
  // The first thing a keyboard reader needs is the way out (or, on a list
  // page, the retry): the first control of the row.
  React.useEffect(() => {
    actionsRef.current?.querySelector<HTMLElement>('a, button')?.focus();
  }, []);

  const canRetry = Boolean(onRetry) && info.retryable;
  const detailsId = React.useId();

  return (
    <Paper
      withBorder
      radius="lg"
      p="xl"
      w="100%"
      maw={520}
      // A failure to load is announced; a missing or refused page is a
      // state the reader arrived in, not an event.
      role={info.kind === 'unavailable' ? 'alert' : 'status'}
      data-testid="load-error"
      data-subject={subjectKey}
      data-kind={info.kind}
      data-status={info.status ?? undefined}
    >
      <Stack align="center" gap="md" ta="center">
        <ThemeIcon variant="light" color={copy.color} size={64} radius="xl">
          <Icon icon={copy.icon} width={34} aria-hidden />
        </ThemeIcon>
        <Title order={2} size="h3">
          {copy.title}
        </Title>
        <Text c="dimmed" maw={420}>
          {copy.text}
        </Text>

        {resourceId && (
          <Group gap={4} wrap="nowrap" maw="100%" justify="center">
            <Text size="xs" c="dimmed">
              ID
            </Text>
            <Code
              data-testid="load-error-id"
              style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}
            >
              {resourceId}
            </Code>
            <CopyButton value={resourceId} timeout={1500}>
              {({ copied, copy: doCopy }) => (
                <Tooltip label={copied ? 'Copied' : `Copy the ${idLabel}`} withArrow>
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color={copied ? 'teal' : 'gray'}
                    onClick={doCopy}
                    aria-label={`Copy the ${idLabel}`}
                  >
                    <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
        )}

        <Group gap="sm" justify="center" ref={actionsRef}>
          {subject.back && (
            <Button
              component="a"
              href={subject.back.href}
              leftSection={<Icon icon={subject.back.icon} width={16} />}
              data-testid="load-error-back"
            >
              {subject.back.label}
            </Button>
          )}
          {canRetry && (
            <Button
              variant={subject.back ? 'default' : 'filled'}
              onClick={onRetry}
              leftSection={<Icon icon="mdi:refresh" width={16} />}
              data-testid="load-error-retry"
            >
              Try again
            </Button>
          )}
          {info.kind === 'forbidden' && (
            <Button
              component="a"
              href={SIGN_IN_PATH}
              onClick={rememberHere}
              variant="default"
              leftSection={<Icon icon="mdi:login" width={16} />}
              data-testid="load-error-sign-in"
            >
              Sign in
            </Button>
          )}
        </Group>

        <Box w="100%">
          <UnstyledButton
            onClick={() => setDetailsOpen((v) => !v)}
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            data-testid="load-error-details-toggle"
          >
            <Group gap={4} wrap="nowrap">
              <Icon icon={detailsOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
              <Text size="xs" c="dimmed">
                Technical details
              </Text>
            </Group>
          </UnstyledButton>
          <Collapse in={detailsOpen} id={detailsId}>
            <Code block mt="xs" ta="left" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {info.status !== null ? `HTTP ${info.status}\n` : ''}
              {info.message}
            </Code>
          </Collapse>
        </Box>
      </Stack>
    </Paper>
  );
};

/**
 * The whole page: the active chrome style's page shell (Glass or Classic)
 * around the card. The header keeps the logo, and in Classic the theme switch
 * and the account badge. No filter panel, no dashboard title.
 */
const DashboardLoadError: React.FC<DashboardLoadErrorProps> = (props) => {
  const glass = useGlassPages();
  const section = SUBJECTS[props.subject ?? 'dashboard'].section;

  if (glass) {
    return (
      <GlassPage section={section} title={section === 'projects' ? 'Projects' : 'Dashboards'}>
        <Center mih={360} py="xl">
          <LoadErrorCard {...props} />
        </Center>
      </GlassPage>
    );
  }

  return (
    <AppShell data-testid="app-shell" header={{ height: 50 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <BrandMark />
          <Group gap="sm" wrap="nowrap">
            <ThemeToggle />
            <ProfileBadge />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Center mih="calc(100dvh - 50px - 2 * var(--mantine-spacing-md))">
          <LoadErrorCard {...props} />
        </Center>
      </AppShell.Main>
    </AppShell>
  );
};

/** Kept under the name the dashboard pages already import. */
export const DashboardLoadErrorCard = LoadErrorCard;

export default DashboardLoadError;

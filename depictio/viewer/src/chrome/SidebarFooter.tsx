import React from 'react';
import {
  Anchor,
  Divider,
  Group,
  HoverCard,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useIsStaticBundle } from 'depictio-react-core';
import DepictioLogo from './DepictioLogo';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import AuthModeBadge from './AuthModeBadge';
import ProfileBadge from './ProfileBadge';
import StaticProvenance from './StaticProvenance';
import { useServerStatus } from '../hooks/useServerStatus';
import { useCurrentUser, type UseCurrentUserResult } from '../hooks/useCurrentUser';

const DOCS_URL = 'https://depictio.github.io/depictio-docs/';

/** How this deployment lets people in, in the precedence the badges use: demo
 *  is a public-mode variant so it has to win over it, and both outrank the
 *  no-login deployments. `null` on a plain authenticated server, where "you
 *  logged in" is not worth a row. */
function accessModeLabel({
  isDemoMode,
  isPublicMode,
  isSingleUserMode,
  authMode,
}: Pick<
  UseCurrentUserResult,
  'isDemoMode' | 'isPublicMode' | 'isSingleUserMode' | 'authMode'
>): string | null {
  if (isDemoMode) return 'Demo mode';
  if (isPublicMode) return 'Public mode';
  if (isSingleUserMode) return 'Single user mode';
  if (authMode === 'unauthenticated') return 'Unauthenticated mode';
  return null;
}

/** What the deployment is, for the logo popover in a server build. Everything
 *  here was previously a permanent chip in the rail. */
const DeploymentDetails: React.FC = () => {
  const { status, version } = useServerStatus();
  const currentUser = useCurrentUser();
  const mode = accessModeLabel(currentUser);

  return (
    <Stack gap="xs">
      <Group gap={8} justify="space-between" wrap="nowrap">
        <Text size="xs" c="dimmed">
          Server
        </Text>
        <Text size="xs">
          {status === 'online' ? (version ? `online — v${version}` : 'online') : 'offline'}
        </Text>
      </Group>
      {mode && (
        <Group gap={8} justify="space-between" wrap="nowrap">
          <Text size="xs" c="dimmed">
            Access
          </Text>
          <Text size="xs">{mode}</Text>
        </Group>
      )}
      <Anchor href={DOCS_URL} target="_blank" rel="noopener noreferrer" size="xs">
        Documentation
      </Anchor>
    </Stack>
  );
};

/**
 * The bottom region of both sidebars — the dashboard rail (`Sidebar`) and the
 * management rail (`AppSidebar`), which carried identical copies of it.
 *
 * One row: the Depictio wordmark on the left, the live controls on the right.
 * It used to be a vertical stack of four full-width chips (a theme switch,
 * "Server online — v1.5.0", "Demo Mode", the profile name), plus — inside a
 * bundle — a heading, a sentence and up to seven provenance rows. That is four
 * to twelve rows of a 250px rail spent on things read once. Here the glyphs
 * stay (each with its label in a tooltip) and everything else moves behind the
 * logo, which doubles as the "what am I looking at" affordance: deployment and
 * version in a server build, export provenance in a bundle.
 *
 * Server, auth and profile chrome is absent (not disabled) in a static bundle:
 * there is no backend to report on and no account to manage, so those controls
 * would be affordances for nothing. The theme switch stays — pure client state,
 * works offline.
 */
const SidebarFooter: React.FC = () => {
  const isStaticBundle = useIsStaticBundle();

  return (
    <Stack gap="xs">
      <Divider w="100%" />
      <Group justify="space-between" align="center" wrap="nowrap" px={4}>
        <HoverCard width={300} position="right-end" withArrow shadow="md" openDelay={150}>
          <HoverCard.Target>
            <UnstyledButton
              aria-label={isStaticBundle ? 'About this export' : 'About this deployment'}
            >
              <Group gap={3} align="center" wrap="nowrap">
                <DepictioLogo height={16} />
                <Icon icon="mdi:chevron-up" width={13} />
              </Group>
            </UnstyledButton>
          </HoverCard.Target>
          <HoverCard.Dropdown>
            {isStaticBundle ? <StaticProvenance /> : <DeploymentDetails />}
          </HoverCard.Dropdown>
        </HoverCard>
        <Group gap="xs" wrap="nowrap">
          <ThemeToggle compact />
          {!isStaticBundle && (
            <>
              <ServerStatusBadge compact />
              <AuthModeBadge compact />
              <ProfileBadge compact />
            </>
          )}
        </Group>
      </Group>
    </Stack>
  );
};

export default SidebarFooter;

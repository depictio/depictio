import React from 'react';
import {
  Anchor,
  Center,
  Divider,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import AuthModeBadge from './AuthModeBadge';
import { useCurrentUser } from '../hooks/useCurrentUser';

export type SidebarSection =
  | 'dashboards'
  | 'projects'
  | 'admin'
  | 'about'
  | 'profile'
  | 'cli-agents';

interface NavEntry {
  key: SidebarSection;
  label: string;
  icon: string;
  href: string;
  color: string;
}

/** Mirrors `depictio/dash/layouts/sidebar.py:186-240` (4 NavLinks with same
 *  icons + colors). The Administration entry is hidden in Dash via a callback
 *  that flips visibility on `is_admin` — we filter the same way client-side. */
const NAV_ENTRIES: NavEntry[] = [
  {
    key: 'dashboards',
    label: 'Dashboards',
    icon: 'material-symbols:dashboard',
    href: '/dashboards-beta',
    color: 'orange',
  },
  {
    key: 'projects',
    label: 'Projects',
    icon: 'mdi:jira',
    href: '/projects-beta',
    color: 'teal',
  },
  {
    key: 'admin',
    label: 'Administration',
    icon: 'material-symbols:settings',
    href: '/admin-beta',
    color: 'blue',
  },
  {
    key: 'about',
    label: 'About',
    icon: 'mingcute:question-line',
    href: '/about-beta',
    color: 'gray',
  },
];

interface AppSidebarProps {
  /** Which entry should be highlighted as the active route. */
  active: SidebarSection;
}

const AppSidebar: React.FC<AppSidebarProps> = ({ active }) => {
  // useComputedColorScheme resolves 'auto' to the actual rendered scheme
  // (dark/light) by reading prefers-color-scheme — useMantineColorScheme
  // can return 'auto' which our equality check would never match.
  const colorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true });
  const { user } = useCurrentUser();

  // Show the Administration link only to admins (matches the Dash sidebar
  // visibility callback at sidebar.py:721-756).
  const entries = NAV_ENTRIES.filter(
    (entry) => entry.key !== 'admin' || Boolean(user?.is_admin),
  );

  return (
    <Stack gap="sm" h="100%" justify="space-between">
      <Stack gap="sm" align="stretch">
        <Center pt="md">
          <Anchor href="/" underline="never">
            {/* Both `logo_black.svg` and `logo_white.svg` ship byte-identical
                (base64-embedded PNG inside an SVG wrapper), so swapping `src`
                does nothing. Apply a CSS filter in dark mode to invert the
                raster while preserving brand hues — same trick as
                `PoweredBy.tsx`. */}
            <img
              src="/dashboard-beta/logos/logo_black.svg"
              alt="depictio"
              style={{
                width: 185,
                display: 'block',
                filter:
                  colorScheme === 'dark' ? 'invert(1) hue-rotate(180deg)' : undefined,
              }}
            />
          </Anchor>
        </Center>
        <Divider />
      </Stack>

      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack gap="xs">
          {entries.map((entry) => {
            const isActive = entry.key === active;
            return (
              <NavLink
                key={entry.href}
                component="a"
                href={entry.href}
                label={
                  <Text size="lg" fw={500} style={{ fontSize: 16 }}>
                    {entry.label}
                  </Text>
                }
                leftSection={<Icon icon={entry.icon} width={25} height={25} />}
                active={isActive}
                color={entry.color}
                variant={isActive ? 'light' : 'subtle'}
                styles={{ root: { padding: 20 } }}
              />
            );
          })}
        </Stack>
      </ScrollArea>

      <Stack gap="xs" align="center">
        <Divider w="100%" />
        <ThemeToggle />
        <ServerStatusBadge />
        <AuthModeBadge />
        <ProfileBadge />
      </Stack>
    </Stack>
  );
};

export default AppSidebar;

import React from 'react';
import {
  Anchor,
  Center,
  Divider,
  NavLink,
  ScrollArea,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import BrandLogo from './BrandLogo';
import PoweredBy from './PoweredBy';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import AuthModeBadge from './AuthModeBadge';
import { brandAccent, useBranding, type BrandRole } from 'depictio-react-core';
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
  /** Brand role this entry takes when the instance defines one. */
  role?: BrandRole;
  /** Used when the brand leaves `role` unset — the historical hue. */
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
    href: '/dashboards',
    role: 'tertiary',
    color: 'orange',
  },
  {
    key: 'projects',
    label: 'Projects',
    icon: 'mdi:jira',
    href: '/projects',
    role: 'secondary',
    color: 'teal',
  },
  {
    key: 'admin',
    label: 'Administration',
    icon: 'material-symbols:settings',
    href: '/admin',
    role: 'primary',
    color: 'blue',
  },
  {
    key: 'about',
    label: 'About',
    icon: 'mingcute:question-line',
    href: '/about',
    color: 'gray',
  },
];

interface AppSidebarProps {
  /** Which entry should be highlighted as the active route. */
  active: SidebarSection;
}

const AppSidebar: React.FC<AppSidebarProps> = ({ active }) => {
  const { user } = useCurrentUser();
  const brand = useBranding();

  // Show the Administration link only to admins (matches the Dash sidebar
  // visibility callback at sidebar.py:721-756).
  const entries = NAV_ENTRIES.filter(
    (entry) => entry.key !== 'admin' || Boolean(user?.is_admin),
  );

  return (
    <Stack gap="sm" h="100%" justify="space-between" data-testid="app-sidebar">
      <Stack gap="sm" align="stretch">
        <Center pt="md">
          <Anchor href="/" underline="never">
            <BrandLogo width={185} />
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
                color={entry.role ? brandAccent(brand, entry.role, entry.color) : entry.color}
                variant={isActive ? 'light' : 'subtle'}
                styles={{ root: { padding: 20 } }}
              />
            );
          })}
        </Stack>
      </ScrollArea>

      <Stack gap="xs" align="center">
        {/* Attribution, below the logo at the top of the rail. It renders only
            once that top slot stops showing the depictio wordmark (see
            PoweredBy): on a branded instance it is the operator's, and without
            this the wordmark would disappear from the app entirely. */}
        <PoweredBy />
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

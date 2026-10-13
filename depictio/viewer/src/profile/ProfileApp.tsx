import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  AppShell,
  Avatar,
  Badge,
  Box,
  Button,
  Center,
  Container,
  FileButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import SignInProviders from '../auth/components/SignInProviders';
import { useGuestSignIn } from '../hooks/useGuestSignIn';
import { Camera, Compass, Crown, ShieldCheck } from 'lucide-react';
import { Icon } from '@iconify/react';
import { GlassPage, STROKE, useGlassPages } from '../chrome/variants/glass/pages';

import {
  clearSession,
  deleteMyAvatar,
  fetchAuthStatus,
  fetchCurrentUserFull,
  listMyGroups,
  uploadMyAvatar,
  type AuthStatusResponse,
  type AvatarInfo,
  type MyGroup,
  type ProfileUser,
} from 'depictio-react-core';

import { AppSidebar } from '../chrome';
import { syncMyAvatar, useMyAvatar } from '../chrome/account';
import { ServerInfoPanel } from '../chrome/server';
import CliAgentsPanel from '../cli-agents/CliAgentsPanel';
import {
  SectionAccordion,
  SettingsSection,
  useOpenSections,
} from '../components/settings/SettingsSections';
import {
  ChromeLookField,
  ThemeField,
  UiScaleField,
} from '../components/settings/preferences';
import { formatDateTime } from '../lib/datetime';
import { usePageTitle } from '../branding';
import { useTourLauncher } from '../walkthrough';
import { squareDownscale } from './avatarImage';
import PasswordForm from './PasswordForm';

const SIDEBAR_KEY = 'profile-sidebar-collapsed';

function useProfileSidebar(): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(SIDEBAR_KEY);
      if (raw == null) return true;
      return JSON.parse(raw) === false;
    } catch {
      return true;
    }
  });
  const toggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, JSON.stringify(!next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  return [opened, toggle];
}

/** The page's sections, in order. Each id doubles as the URL hash that opens
 *  it (`/profile#cli-agents`), so the ids are a contract: the old `/cli-agents`
 *  route lands on one of them, and docs may link to them. */
const SECTION_IDS = [
  'account',
  'password',
  'cli-agents',
  'preferences',
  'getting-started',
  'server',
] as const;
type SectionId = (typeof SECTION_IDS)[number];

const sectionTestId = (id: SectionId) => `settings-section-${id}`;

function sectionFromHash(): SectionId | null {
  const id = window.location.hash.replace(/^#/, '');
  return (SECTION_IDS as readonly string[]).includes(id) ? (id as SectionId) : null;
}

/** Mirrors `depictio/dash/layouts/profile.py` button enable/disable rules.
 *  A gated action is disabled, not hidden, so each one carries the reason
 *  (null = available) for its tooltip. */
function actionStates(status: AuthStatusResponse | null): {
  logoutReason: string | null;
  passwordReason: string | null;
} {
  const isPublic = Boolean(status?.is_public_mode);
  const isSingle = Boolean(status?.is_single_user_mode);
  const isDemo = Boolean(status?.is_demo_mode);
  return {
    logoutReason:
      isPublic || isSingle
        ? 'There is no sign-in to end in public or single-user mode.'
        : null,
    passwordReason:
      isSingle || isPublic || isDemo
        ? 'The password cannot be changed in single-user, public or demo mode.'
        : null,
  };
}

/** Why the picture cannot be changed, or null. A gated action is disabled, not
 *  hidden, so the reason rides on its tooltip. Mirrors the server's refusal
 *  (`_require_avatar_editor`): the server stays the authority. */
function avatarDisabledReason(user: ProfileUser, status: AuthStatusResponse | null): string | null {
  if (status?.is_demo_mode) return 'Profile pictures cannot be changed in demo mode.';
  if (user.is_anonymous) return 'Sign in to set a profile picture.';
  if (user.is_temporary || status?.is_public_mode) {
    return 'Temporary accounts cannot have a profile picture. Create an account to set one.';
  }
  return null;
}

const PAGE_TITLE = 'Account settings';

/** Restarts the guided tour. Disabled, not hidden, where the deployment turned
 *  tours off: the reason is worth knowing, and the section stays where docs
 *  point to. Restarting here works because the builder tour's first step moves
 *  on by itself and `start` takes the explorer tour to /dashboards. */
const GettingStarted: React.FC = () => {
  const tour = useTourLauncher();
  return (
    <Stack gap="sm" align="flex-start">
      <Text size="sm" c="dimmed">
        A short walkthrough of the pages and the controls you will use most.
      </Text>
      <Tooltip label={tour.reason} withArrow disabled={tour.reason === null}>
        {/* A disabled button swallows pointer events; the span carries the tooltip. */}
        <span>
          <Button
            variant="light"
            disabled={!tour.available}
            onClick={tour.start}
            leftSection={<Compass size={16} strokeWidth={1.8} aria-hidden />}
            data-testid="getting-started-tour"
          >
            {tour.label}
          </Button>
        </span>
      </Tooltip>
    </Stack>
  );
};

const ProfileApp: React.FC = () => {
  const [user, setUser] = useState<ProfileUser | null>(null);
  const guest = useGuestSignIn();
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [myGroups, setMyGroups] = useState<MyGroup[]>([]);
  const [loading, setLoading] = useState(true);
  // Account is open on a first visit; the rest start folded and are remembered.
  const [openSections, setOpenSections] = useOpenSections('depictio-account-sections', [
    'account',
  ]);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useProfileSidebar();

  usePageTitle(PAGE_TITLE);
  const glass = useGlassPages();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchCurrentUserFull(),
      fetchAuthStatus(),
      // Groups are decorative on this page — never fail the whole profile
      // when the endpoint is unavailable (e.g. anonymous session).
      listMyGroups().catch(() => [] as MyGroup[]),
    ])
      .then(([u, s, g]) => {
        if (cancelled) return;
        setUser(u);
        setStatus(s);
        setMyGroups(g);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Deep links: `#<section>` opens that section for this visit and scrolls it
  // into view, on load and whenever the hash changes (a link clicked on this
  // very page does not reload it). Opening a section by hand does not write
  // the hash. The opening is transient (`revealed`), kept out of the remembered
  // list: a link must not leave its target open on every later visit.
  const [revealed, setRevealed] = useState<string[]>([]);
  const visibleSections = [...new Set([...openSections, ...revealed])];
  const handleSectionsChange = useCallback(
    (value: string[]) => {
      setRevealed((prev) => prev.filter((id) => value.includes(id)));
      // A revealed section only enters the remembered list if it was there.
      setOpenSections(value.filter((id) => openSections.includes(id) || !revealed.includes(id)));
    },
    [openSections, revealed, setOpenSections],
  );
  const ready = !loading && user !== null;

  useEffect(() => {
    if (!ready) return undefined;
    let timer: number | undefined;
    const reveal = () => {
      const id = sectionFromHash();
      if (!id) return;
      setRevealed((prev) => (prev.includes(id) ? prev : [...prev, id]));
      // After the section's panel has started to open: scrolling earlier
      // aims at its still-folded height.
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        document
          .querySelector(`[data-testid="${sectionTestId(id)}"]`)
          ?.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' });
      }, 150);
    };
    reveal();
    window.addEventListener('hashchange', reveal);
    return () => {
      window.removeEventListener('hashchange', reveal);
      window.clearTimeout(timer);
    };
  }, [ready]);

  const handleLogout = useCallback(() => {
    clearSession();
    window.location.assign('/auth');
  }, []);

  const states = actionStates(status);

  // Keeps this page's copy of the auth status in step with an upload or a
  // removal, so a section that remounts does not tell the shared avatar store
  // a stale stamp. Every avatar on the page follows through `syncMyAvatar`.
  const handleAvatarChange = useCallback((info: AvatarInfo | null) => {
    setStatus((prev) =>
      prev?.user
        ? {
            ...prev,
            user: {
              ...prev.user,
              avatar_updated_at: info?.updated_at ?? null,
              avatar_source: info?.source ?? null,
              avatar_provider: info?.provider ?? null,
            },
          }
        : prev,
    );
    syncMyAvatar(info?.updated_at ?? null);
  }, []);

  const body = loading ? (
    <Center mih={300}>
      <Loader />
    </Center>
  ) : !user ? (
    <Center mih={300}>
      <Stack align="center" gap="xs">
        <Icon icon="mdi:account-off" width={32} color="var(--mantine-color-gray-6)" />
        <Text c="dimmed">No authenticated user.</Text>
        <Button component="a" href="/auth" variant="light">
          Sign In
        </Button>
      </Stack>
    </Center>
  ) : (
    <Stack gap="md" maw={860} data-testid="account-settings">
      {guest.available && (
        <Alert color="blue" title="You are browsing as a guest" data-testid="guest-sign-in-note">
          <Stack gap="xs" align="flex-start">
            <Text size="sm">
              This temporary account expires on its own, and so do the copies of dashboards you
              make with it. Sign in to leave comments.
            </Text>
            <Stack gap="xs" w="100%" maw={320} data-testid="guest-sign-in-profile">
              <SignInProviders
                googleEnabled={guest.googleEnabled}
                samlEnabled={guest.samlEnabled}
                samlLabel={guest.samlLabel}
              />
            </Stack>
          </Stack>
        </Alert>
      )}
      <SectionAccordion
        value={visibleSections}
        onChange={handleSectionsChange}
        testId="account-sections"
      >
        <SettingsSection
          value="account"
          icon="mdi:account-circle-outline"
          title="Account"
          subtitle="Who you are signed in as"
          testId={sectionTestId('account')}
        >
          <AccountDetails
            user={user}
            status={status}
            groups={myGroups}
            avatarDisabledReason={avatarDisabledReason(user, status)}
            onAvatarChange={handleAvatarChange}
          />
        </SettingsSection>

        <SettingsSection
          value="password"
          icon="mdi:lock-outline"
          title="Password"
          subtitle="Change the password you sign in with"
          testId={sectionTestId('password')}
        >
          <PasswordForm disabledReason={states.passwordReason} />
        </SettingsSection>

        <SettingsSection
          value="cli-agents"
          icon="mdi:console-line"
          title="CLI agents"
          subtitle="Long-lived tokens for the Depictio command line"
          testId={sectionTestId('cli-agents')}
        >
          {/* Mounted while open: its token list is fetched on mount, and a
              public-mode visitor who never opens it should not trigger it. */}
          {visibleSections.includes('cli-agents') && <CliAgentsPanel />}
        </SettingsSection>

        <SettingsSection
          value="preferences"
          icon="mdi:tune-variant"
          title="Preferences"
          subtitle="Only for you, saved in this browser"
          testId={sectionTestId('preferences')}
        >
          <Stack gap="lg">
            <ThemeField />
            <ChromeLookField />
            <UiScaleField />
          </Stack>
        </SettingsSection>

        <SettingsSection
          value="getting-started"
          icon="mdi:compass-outline"
          title="Getting started"
          subtitle="Replay the guided tour of Depictio"
          testId={sectionTestId('getting-started')}
        >
          <GettingStarted />
        </SettingsSection>

        <SettingsSection
          value="server"
          icon="mdi:server-outline"
          title="Server"
          subtitle="Version and status of this Depictio instance"
          testId={sectionTestId('server')}
        >
          <ServerInfoPanel variant="section" />
        </SettingsSection>
      </SectionAccordion>

      <Group justify="flex-end">
        <Tooltip label={states.logoutReason} withArrow disabled={states.logoutReason === null}>
          {/* A disabled button swallows pointer events; the span carries the tooltip. */}
          <span>
            <Button
              variant="default"
              disabled={states.logoutReason !== null}
              onClick={handleLogout}
              leftSection={<Icon icon="mdi:logout" width={18} />}
              data-testid="logout-button"
            >
              Sign out
            </Button>
          </span>
        </Tooltip>
      </Group>
    </Stack>
  );

  if (glass) {
    return (
      <GlassPage
        section="profile"
        title={PAGE_TITLE}
        description="Your account, password, CLI access and preferences, and the server you are connected to."
      >
        {body}
      </GlassPage>
    );
  }

  return (
    <AppShell
      data-testid="app-shell"
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon icon="mdi:account-circle" width={26} color="var(--mantine-color-violet-6)" />
            <Title order={3} c="violet">
              {PAGE_TITLE}
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="profile" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Container size="lg" p="xl" fluid>
          {body}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
};

/** The provider's display name for the "From your ... account" line. */
function providerLabel(provider: string | null | undefined): string {
  if (!provider) return 'identity provider';
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** Avatar with its editor, then the account facts. Without a picture the
 *  avatar shows initials from the address's local part (`jane.doe@x` reads
 *  "JD"), drawn by Mantine instead of fetched from an external avatar service,
 *  so nothing leaves the instance. A picture is cropped square in the browser
 *  before upload; the server re-encodes it anyway. */
const AccountDetails: React.FC<{
  user: ProfileUser;
  status: AuthStatusResponse | null;
  groups: MyGroup[];
  avatarDisabledReason: string | null;
  onAvatarChange: (info: AvatarInfo | null) => void;
}> = ({ user, status, groups, avatarDisabledReason: disabledReason, onAvatarChange }) => {
  const avatarUrl = useMyAvatar();
  const [busy, setBusy] = useState<'upload' | 'remove' | null>(null);
  const hasPicture = Boolean(status?.user?.avatar_updated_at);
  const fromProvider = hasPicture && status?.user?.avatar_source === 'provider';

  const handleFile = useCallback(
    async (file: File | null) => {
      if (!file) return;
      setBusy('upload');
      try {
        const prepared = await squareDownscale(file);
        const info = await uploadMyAvatar(prepared);
        onAvatarChange(info);
        notifications.show({
          color: 'teal',
          title: 'Profile picture updated',
          message: 'It now shows next to your name.',
          autoClose: 2500,
        });
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Could not update the picture',
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setBusy(null);
      }
    },
    [onAvatarChange],
  );

  const handleRemove = useCallback(async () => {
    setBusy('remove');
    try {
      await deleteMyAvatar();
      onAvatarChange(null);
      notifications.show({
        color: 'teal',
        title: 'Profile picture removed',
        message: 'Your initials show again.',
        autoClose: 2500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not remove the picture',
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [onAvatarChange]);

  return (
    <Stack gap="md">
      <Group gap="md" wrap="nowrap" align="center">
        {/* Immich-style: the picture is edited from a small camera button on
            the avatar itself rather than a row of buttons beside it. */}
        <Box pos="relative" style={{ flexShrink: 0 }}>
          <Avatar
            size={72}
            radius="xl"
            color="initials"
            src={avatarUrl}
            alt=""
            name={user.email.split('@')[0].replace(/[._-]+/g, ' ')}
            // The <img> exists only with a picture, so tests can tell it from initials.
            imageProps={{ 'data-testid': 'avatar-image' } as React.ImgHTMLAttributes<HTMLImageElement>}
            data-testid="profile-avatar"
          />
          <Tooltip
            label={disabledReason ?? (hasPicture ? 'Change picture' : 'Add a picture')}
            withArrow
          >
            {/* A disabled button swallows pointer events; the span carries the tooltip. */}
            <Box component="span" pos="absolute" right={-4} bottom={-4}>
              <FileButton
                onChange={handleFile}
                accept="image/png,image/jpeg,image/webp,image/gif"
                disabled={disabledReason !== null || busy !== null}
              >
                {(props) => (
                  <ActionIcon
                    {...props}
                    variant="default"
                    radius="xl"
                    size={28}
                    loading={busy === 'upload'}
                    disabled={disabledReason !== null || busy !== null}
                    aria-label={hasPicture ? 'Change picture' : 'Add a picture'}
                    data-testid="avatar-change"
                  >
                    <Camera size={14} />
                  </ActionIcon>
                )}
              </FileButton>
            </Box>
          </Tooltip>
        </Box>
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Text fw={600} style={{ wordBreak: 'break-word' }}>
            {user.email}
          </Text>
          <Text size="xs" c="dimmed">
            {user.is_admin ? 'Administrator' : 'User'}
            {fromProvider && ` · picture from your ${providerLabel(status?.user?.avatar_provider)} account`}
          </Text>
          {hasPicture && (
            <Tooltip label={disabledReason} withArrow disabled={disabledReason === null}>
              <span style={{ alignSelf: 'flex-start' }}>
                <Button
                  variant="subtle"
                  color="gray"
                  size="compact-xs"
                  px={0}
                  loading={busy === 'remove'}
                  disabled={disabledReason !== null || busy !== null}
                  onClick={handleRemove}
                  data-testid="avatar-remove"
                >
                  Remove picture
                </Button>
              </span>
            </Tooltip>
          )}
        </Stack>
      </Group>
      <Stack gap="xs">
        <UserInfoRow label="Email" value={user.email} />
        {user.display_name && <UserInfoRow label="Name" value={user.display_name} />}
        {user.title && <UserInfoRow label="Title" value={user.title} />}
        <UserInfoRow label="Role" value={user.is_admin ? 'Administrator' : 'User'} />
        <GroupsInfoRow groups={groups} />
        <UserInfoRow label="Database ID" value={user.id || 'N/A'} />
        <UserInfoRow
          label="Registration date"
          value={user.registration_date ? formatDateTime(user.registration_date) : 'N/A'}
        />
        <UserInfoRow
          label="Last login"
          value={user.last_login ? formatDateTime(user.last_login) : 'N/A'}
        />
      </Stack>
    </Stack>
  );
};

const UserInfoRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <Paper
    p="xs"
    px="sm"
    radius="md"
    withBorder
    data-testid={`profile-info-${label.toLowerCase().replace(/\s+/g, '-')}`}
  >
    <Group justify="space-between" wrap="nowrap" align="flex-start">
      <Text fw={500} size="sm">
        {label}
      </Text>
      <Text size="sm" ta="right" style={{ wordBreak: 'break-word' }}>
        {value}
      </Text>
    </Group>
  </Paper>
);

/** Same Paper chrome as UserInfoRow, but the value is a badge-per-group.
 *  Crown marks the groups the user is P.I. of, shield the ones they
 *  administer. Each badge deep-links into /groups, which is the only entry
 *  point to the personal groups page (the sidebar entry lives in /admin). */
const GroupsInfoRow: React.FC<{ groups: MyGroup[] }> = ({ groups }) => {
  const glass = useGlassPages();
  return (
  <Paper p="xs" px="sm" radius="md" withBorder data-testid="profile-info-groups">
    <Group justify="space-between" wrap="nowrap" align="flex-start">
      <Text fw={500} size="sm">
        Groups
      </Text>
      {groups.length === 0 ? (
        <Text size="sm" c="dimmed">
          None
        </Text>
      ) : (
        <Group gap={6} justify="flex-end" style={{ flex: 1 }}>
          {groups.map((group) => (
            <Badge
              key={group.id}
              component="a"
              href={`/groups?group=${group.id}`}
              style={{ cursor: 'pointer' }}
              color={group.is_pi ? 'yellow' : group.is_group_admin ? 'blue' : 'gray'}
              variant="light"
              size="sm"
              radius="sm"
              leftSection={
                group.is_pi ? (
                  glass ? (
                    <Crown size={12} strokeWidth={STROKE} aria-hidden />
                  ) : (
                    <Icon icon="mdi:crown-outline" width={12} />
                  )
                ) : group.is_group_admin ? (
                  glass ? (
                    <ShieldCheck size={12} strokeWidth={STROKE} aria-hidden />
                  ) : (
                    <Icon icon="mdi:shield-account-outline" width={12} />
                  )
                ) : undefined
              }
            >
              {group.name}
            </Badge>
          ))}
        </Group>
      )}
    </Group>
  </Paper>
  );
};

export default ProfileApp;

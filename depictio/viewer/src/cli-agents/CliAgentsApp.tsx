import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  createLongLivedToken,
  deleteLongLivedToken,
  fetchAuthStatus,
  generateAgentConfig,
  listLongLivedTokens,
  type AuthStatusResponse,
  type CliAgentConfig,
  type CliToken,
} from 'depictio-react-core';

import { AppSidebar } from '../chrome';
import { brandColors } from '../profile/colors';
import CreateTokenModal from './CreateTokenModal';
import DeleteTokenModal from './DeleteTokenModal';
import DisplayTokenModal from './DisplayTokenModal';

const SIDEBAR_KEY = 'cli-agents-sidebar-collapsed';

function useCliAgentsSidebar(): [boolean, () => void] {
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

const CliAgentsApp: React.FC = () => {
  const [tokens, setTokens] = useState<CliToken[]>([]);
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [generatedConfig, setGeneratedConfig] = useState<CliAgentConfig | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<CliToken | null>(null);

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [displayOpened, { open: openDisplay, close: closeDisplay }] = useDisclosure(false);
  const [deleteOpened, { open: openDelete, close: closeDelete }] = useDisclosure(false);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useCliAgentsSidebar();

  useEffect(() => {
    document.title = 'Depictio — CLI Agents';
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([listLongLivedTokens(), fetchAuthStatus()])
      .then(([list, s]) => {
        if (cancelled) return;
        setTokens(list);
        setStatus(s);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        notifications.show({
          color: 'red',
          title: 'Failed to load CLI configurations',
          message: err.message,
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const isAddDisabled = Boolean(status?.is_public_mode || status?.is_single_user_mode);

  const handleCreate = useCallback(
    async (name: string) => {
      const created = await createLongLivedToken(name);
      // Generate the YAML config; the modal tolerates null and shows a
      // graceful fallback (matches Dash behaviour).
      let config: CliAgentConfig | null = null;
      try {
        config = await generateAgentConfig(created);
      } catch (err) {
        console.error('Failed to generate CLI config:', err);
      }
      setGeneratedConfig(config);
      closeCreate();
      openDisplay();
      refresh();
      notifications.show({
        color: 'teal',
        title: 'CLI configuration created',
        message: `"${name}" is ready.`,
        autoClose: 2500,
      });
    },
    [closeCreate, openDisplay, refresh],
  );

  const handleDeleteRequest = useCallback(
    (token: CliToken) => {
      setTokenToDelete(token);
      openDelete();
    },
    [openDelete],
  );

  const handleConfirmDelete = useCallback(async () => {
    if (!tokenToDelete) return;
    try {
      await deleteLongLivedToken(tokenToDelete._id);
      notifications.show({
        color: 'teal',
        title: 'Configuration deleted',
        message: tokenToDelete.name || 'Token removed.',
        autoClose: 2000,
      });
      closeDelete();
      setTokenToDelete(null);
      refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Delete failed',
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [tokenToDelete, closeDelete, refresh]);

  return (
    <AppShell
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
            <Icon icon="mdi:console-line" width={26} color={brandColors.green} />
            <Title order={3} c={brandColors.green}>
              CLI Agents
            </Title>
          </Group>
          <Button
            component="a"
            href="/profile-beta"
            variant="subtle"
            color="gray"
            leftSection={<Icon icon="mdi:arrow-left" width={16} />}
          >
            Back to Profile
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="cli-agents" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Container size="lg" p="md">
          {/* Header card — title + description + add button.
              Mirrors `tokens_management.py:209-280`. */}
          <Center mb="md">
            <Paper
              shadow="xs"
              p="xl"
              withBorder
              radius="md"
              style={{
                width: '100%',
                maxWidth: 700,
                borderColor: `${brandColors.teal}40`,
              }}
            >
              <Stack align="center" gap="xs">
                <Group gap="xs" justify="center">
                  <Icon
                    icon="mdi:console-line"
                    width={32}
                    height={32}
                    color={brandColors.green}
                  />
                  <Title order={2} c={brandColors.green}>
                    Depictio-CLI Configurations
                  </Title>
                </Group>
                <Text ta="center" c="gray" size="sm">
                  Security configurations to access Depictio via the command line interface.
                </Text>
                <Button
                  leftSection={<Icon icon="mdi:plus-circle" width={20} color="white" />}
                  radius="md"
                  size="md"
                  mt="md"
                  disabled={isAddDisabled}
                  onClick={openCreate}
                  styles={{
                    root: {
                      backgroundColor: isAddDisabled ? undefined : brandColors.green,
                    },
                  }}
                >
                  Add New Configuration
                </Button>
              </Stack>
            </Paper>
          </Center>

          {/* Token list — empty state or stack of cards */}
          <Box mt="md">
            {loading ? (
              <Center mih={200}>
                <Loader />
              </Center>
            ) : tokens.length === 0 ? (
              <EmptyTokensState />
            ) : (
              <TokensList tokens={tokens} onDelete={handleDeleteRequest} />
            )}
          </Box>
        </Container>
      </AppShell.Main>

      <CreateTokenModal
        opened={createOpened}
        onClose={closeCreate}
        onSubmit={handleCreate}
        existingNames={tokens.map((t) => t.name || '').filter(Boolean)}
      />
      <DeleteTokenModal
        opened={deleteOpened}
        onClose={() => {
          closeDelete();
          setTokenToDelete(null);
        }}
        onConfirm={handleConfirmDelete}
      />
      <DisplayTokenModal
        opened={displayOpened}
        onClose={() => {
          closeDisplay();
          setGeneratedConfig(null);
        }}
        config={generatedConfig}
      />
    </AppShell>
  );
};

const EmptyTokensState: React.FC = () => (
  <Center>
    <Paper
      shadow="sm"
      radius="md"
      p="xl"
      withBorder
      style={{
        width: '100%',
        maxWidth: 700,
        borderColor: `${brandColors.teal}40`,
      }}
    >
      <Stack align="center" gap="sm">
        <Icon
          icon="bi:terminal-x"
          width={64}
          height={64}
          color={`${brandColors.blue}80`}
        />
        <Text ta="center" fw="bold" size="xl" c={brandColors.blue}>
          No CLI Configurations Available
        </Text>
        <Text ta="center" c="gray" size="sm">
          Add a new configuration to access Depictio via the command line interface.
        </Text>
      </Stack>
    </Paper>
  </Center>
);

interface TokensListProps {
  tokens: CliToken[];
  onDelete: (token: CliToken) => void;
}

const TokensList: React.FC<TokensListProps> = ({ tokens, onDelete }) => (
  <Stack
    style={{
      width: '100%',
      maxWidth: 800,
      marginLeft: 'auto',
      marginRight: 'auto',
    }}
    gap="xs"
  >
    {tokens.map((token) => (
      <Paper
        key={token._id}
        p="md"
        withBorder
        radius="md"
        shadow="xs"
        style={{ borderColor: `${brandColors.teal}40` }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Icon
              icon="mdi:key-variant"
              width={28}
              color={`${brandColors.blue}80`}
            />
            <Stack gap={0}>
              <Text fw="bold" size="lg" c={brandColors.blue}>
                {token.name || '(unnamed)'}
              </Text>
              <Text size="xs" c="gray">
                Expires: {token.expire_datetime}
              </Text>
            </Stack>
          </Group>
          <Button
            variant="subtle"
            radius="md"
            leftSection={<Icon icon="mdi:delete" width={16} />}
            onClick={() => onDelete(token)}
            styles={{ root: { color: brandColors.red } }}
          >
            Delete
          </Button>
        </Group>
      </Paper>
    ))}
  </Stack>
);

export default CliAgentsApp;

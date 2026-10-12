import React, { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Center, Group, Loader, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { Plus } from 'lucide-react';

import {
  createLongLivedToken,
  deleteLongLivedToken,
  fetchAuthStatus,
  generateAgentConfig,
  listLongLivedTokens,
  type AuthStatusResponse,
  type CliAgentConfig,
  type CliToken,
  type TokenScope,
} from 'depictio-react-core';

import CreateTokenModal from './CreateTokenModal';
import DeleteTokenModal from './DeleteTokenModal';
import DisplayTokenModal from './DisplayTokenModal';

/**
 * Long-lived CLI tokens: list, create (which shows the generated agent config
 * once) and delete. Lives in the account settings page as its `cli-agents`
 * section; it used to be a page of its own, and keeps the same behaviour,
 * including being disabled in public mode, where visitors are temporary users.
 */
const CliAgentsPanel: React.FC = () => {
  const [tokens, setTokens] = useState<CliToken[]>([]);
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [generatedConfig, setGeneratedConfig] = useState<CliAgentConfig | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<CliToken | null>(null);

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [displayOpened, { open: openDisplay, close: closeDisplay }] = useDisclosure(false);
  const [deleteOpened, { open: openDelete, close: closeDelete }] = useDisclosure(false);

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

  const isAddDisabled = Boolean(status?.is_public_mode);

  const handleCreate = useCallback(
    async (name: string, scopes: TokenScope[] | null) => {
      const created = await createLongLivedToken(name, scopes);
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
    <Stack gap="sm" data-testid="cli-agents-panel">
      <Group justify="space-between" align="center" wrap="nowrap">
        <Text size="xs" c="dimmed" lh={1.35}>
          Security configurations to access Depictio via the command line interface.
        </Text>
        <Tooltip
          label="Not available in public mode"
          withArrow
          disabled={!isAddDisabled}
        >
          {/* A disabled button swallows pointer events; the span carries the tooltip. */}
          <span style={{ flexShrink: 0 }}>
            <Button
              size="xs"
              variant="default"
              leftSection={<Plus size={14} />}
              disabled={isAddDisabled}
              onClick={openCreate}
              data-testid="add-cli-config-btn"
            >
              Add configuration
            </Button>
          </span>
        </Tooltip>
      </Group>

      {loading ? (
        <Center mih={120}>
          <Loader size="sm" />
        </Center>
      ) : tokens.length === 0 ? (
        <EmptyTokensState />
      ) : (
        <TokensList tokens={tokens} onDelete={handleDeleteRequest} />
      )}

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
    </Stack>
  );
};

const EmptyTokensState: React.FC = () => (
  <Paper p="md" radius="md" withBorder data-testid="cli-agents-empty">
    <Group gap="sm" wrap="nowrap">
      <Icon icon="bi:terminal-x" width={32} height={32} color="var(--mantine-color-dimmed)" />
      <Stack gap={0}>
        <Text fw={600} size="sm">
          No CLI configurations yet
        </Text>
        <Text c="dimmed" size="xs">
          Add a configuration to access Depictio via the command line interface.
        </Text>
      </Stack>
    </Group>
  </Paper>
);

/** Full access for legacy/unscoped tokens, otherwise one badge per scope. */
const TokenScopeBadges: React.FC<{ scopes: TokenScope[] | null }> = ({ scopes }) => (
  <Group gap={4} mt={4} data-testid="cli-token-scopes">
    {scopes === null ? (
      <Badge size="xs" variant="light" color="gray">
        Full access
      </Badge>
    ) : (
      scopes.map((scope) => (
        <Badge key={scope} size="xs" variant="light">
          {scope.replace('_', ' ')}
        </Badge>
      ))
    )}
  </Group>
);

interface TokensListProps {
  tokens: CliToken[];
  onDelete: (token: CliToken) => void;
}

const TokensList: React.FC<TokensListProps> = ({ tokens, onDelete }) => (
  <Stack gap="xs" data-testid="cli-agents-list">
    {tokens.map((token) => (
      <Paper key={token._id} p="sm" withBorder radius="md">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Icon icon="mdi:key-variant" width={24} color="var(--mantine-color-dimmed)" />
            <Stack gap={0}>
              <Text fw={600} size="sm">
                {token.name || '(unnamed)'}
              </Text>
              <Text size="xs" c="dimmed">
                Expires: {token.expire_datetime}
              </Text>
              <TokenScopeBadges scopes={token.scopes} />
            </Stack>
          </Group>
          <Button
            variant="subtle"
            color="red"
            size="xs"
            leftSection={<Icon icon="mdi:delete" width={16} />}
            onClick={() => onDelete(token)}
          >
            Delete
          </Button>
        </Group>
      </Paper>
    ))}
  </Stack>
);

export default CliAgentsPanel;

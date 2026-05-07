import React from 'react';
import {
  Alert,
  Anchor,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  PasswordInput,
  Tooltip,
  ActionIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useAISession, useAIStore } from '../store';

interface Props {
  dashboardId: string;
  /** Optional override for the model dropdown; defaults to a small curated
   *  list of provider strings supported by LiteLLM. */
  modelOptions?: { value: string; label: string }[];
}

const DEFAULT_MODEL_OPTIONS = [
  { value: '', label: 'Server default' },
  {
    value: 'openrouter/anthropic/claude-sonnet-4-6',
    label: 'OpenRouter — Claude Sonnet 4.6',
  },
  {
    value: 'openrouter/anthropic/claude-opus-4-7',
    label: 'OpenRouter — Claude Opus 4.7',
  },
  { value: 'anthropic/claude-sonnet-4-6', label: 'Anthropic — Sonnet 4.6' },
  { value: 'openai/gpt-4o', label: 'OpenAI — gpt-4o' },
  { value: 'gemini/gemini-1.5-pro', label: 'Gemini — 1.5 Pro' },
];

/**
 * Section meant to be slotted inside the dashboard SettingsDrawer.
 * Captures the user's LLM API key (per-dashboard, never persisted) and
 * an optional model override.
 */
const AIKeySection: React.FC<Props> = ({ dashboardId, modelOptions }) => {
  const session = useAISession(dashboardId);
  const setKey = useAIStore((s) => s.setKey);
  const setModel = useAIStore((s) => s.setModel);
  const clearKey = useAIStore((s) => s.clearKey);

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Group gap={6} align="center">
          <Icon icon="material-symbols:smart-toy-outline" width={18} />
          <Text fw={600}>AI assistant</Text>
        </Group>
        {session.llmKey && (
          <Tooltip label="Clear key for this dashboard">
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={() => clearKey(dashboardId)}
              aria-label="Clear API key"
            >
              <Icon icon="material-symbols:close" width={16} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>

      <PasswordInput
        label="LLM API key"
        description="Saved in your browser (localStorage) per dashboard so you don't need to re-enter it after a refresh. Sent only to your chosen provider."
        placeholder="sk-or-... / sk-ant-... / sk-..."
        value={session.llmKey}
        onChange={(e) => setKey(dashboardId, e.currentTarget.value)}
        autoComplete="off"
      />

      <Select
        label="Model"
        data={modelOptions ?? DEFAULT_MODEL_OPTIONS}
        value={session.model || ''}
        onChange={(v) => setModel(dashboardId, v ?? '')}
        searchable
        clearable={false}
        comboboxProps={{ withinPortal: true }}
      />

      {!session.llmKey && (
        <Alert
          color="blue"
          variant="light"
          icon={<Icon icon="material-symbols:info-outline" width={16} />}
        >
          <Text size="xs">
            Bring your own key. Recommended: an{' '}
            <Anchor
              href="https://openrouter.ai/keys"
              target="_blank"
              rel="noopener"
            >
              OpenRouter key
            </Anchor>{' '}
            covers most providers.
          </Text>
        </Alert>
      )}
    </Stack>
  );
};

export default AIKeySection;

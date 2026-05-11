/**
 * AI fill modal — sparkle button companion on the component builder.
 *
 * The user is already in the builder with a component type + data
 * collection selected. They type a natural-language prompt; the modal
 * calls /ai/component-from-prompt; on success it hands the validated
 * dict to the host via `onApply`. The host (viewer) drops the dict
 * into `useBuilderStore.config` — the existing per-type builder + live
 * preview do everything else.
 *
 * The modal stays open after a successful apply so the user can iterate
 * ("now color it by sample") without losing context, but the host can
 * always pass `closeOnApply` to dismiss immediately.
 */

import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useComponentFromPrompt } from '../hooks';
import { useAISession } from '../store';
import type {
  ComponentFromPromptResponse,
  ComponentType,
} from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  componentType: ComponentType;
  dataCollectionId: string;
  /** Current StoredMetadata when revising an existing component. When
   *  set, the prompt is sent as a revision request rather than a fresh
   *  build. */
  current?: Record<string, unknown> | null;
  /** Host-owned hydration of the builder store. Called with the
   *  validated component dict — field names match StoredMetadata, so the
   *  host can drop it straight into the builder's `config`. */
  onApply: (parsed: Record<string, unknown>) => void;
  /** When true (default), dismiss the modal after a successful apply.
   *  Set to false to keep it open for iteration. */
  closeOnApply?: boolean;
}

const AiFillModal: React.FC<Props> = ({
  opened,
  onClose,
  dashboardId,
  componentType,
  dataCollectionId,
  current,
  onApply,
  closeOnApply = true,
}) => {
  const session = useAISession(dashboardId);
  const { run, pending, error, lastResponse } = useComponentFromPrompt(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [showYaml, setShowYaml] = useState(false);

  const canSend = Boolean(
    prompt.trim() && session.llmKey && dataCollectionId && !pending,
  );

  async function send() {
    if (!canSend) return;
    let res: ComponentFromPromptResponse;
    try {
      res = await run({
        data_collection_id: dataCollectionId,
        prompt: prompt.trim(),
        component_type: componentType,
        current: current ?? null,
      });
    } catch {
      // useComponentFromPrompt surfaces the error via its `error` state;
      // the alert below will render it.
      return;
    }
    onApply(res.parsed);
    setPrompt('');
    if (closeOnApply) onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <Icon
            icon="material-symbols:auto-fix"
            width={18}
            color="var(--mantine-color-violet-6)"
          />
          <Text fw={600}>
            AI fill — {componentType}
            {current ? ' (revise)' : ''}
          </Text>
          {session.model && (
            <Badge size="xs" variant="light" color="blue">
              {session.model.split('/').pop()}
            </Badge>
          )}
        </Group>
      }
      size="lg"
    >
      <Stack gap="sm">
        {!session.llmKey && (
          <Alert color="yellow" variant="light">
            Set an LLM API key from the dashboard settings drawer to use AI fill.
          </Alert>
        )}
        {!dataCollectionId && (
          <Alert color="yellow" variant="light">
            Pick a data collection in the previous step first.
          </Alert>
        )}
        <Textarea
          placeholder={
            current
              ? 'e.g. "make it a log-scale histogram", "color by sample"'
              : 'e.g. "histogram of read length grouped by sample"'
          }
          value={prompt}
          onChange={(e) => setPrompt(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void send();
            }
          }}
          autosize
          minRows={3}
          maxRows={8}
          disabled={pending}
        />
        {error && (
          <Alert color="red" variant="light" title="AI fill failed">
            <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
              {error}
            </Text>
          </Alert>
        )}
        {lastResponse && !error && (
          <Stack gap={4}>
            <Group gap={6} align="center">
              <Icon
                icon="material-symbols:check-circle"
                width={14}
                color="var(--mantine-color-teal-6)"
              />
              <Text size="xs" c="dimmed">
                Applied {lastResponse.component_type}
                {lastResponse.validation_attempts > 1
                  ? ` (retry ${lastResponse.validation_attempts})`
                  : ''}
                {lastResponse.explanation ? ` — ${lastResponse.explanation}` : ''}
              </Text>
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                ml="auto"
                onClick={() => setShowYaml((v) => !v)}
              >
                {showYaml ? 'Hide YAML' : 'Show YAML'}
              </Button>
            </Group>
            {showYaml && (
              <ScrollArea style={{ maxHeight: 240 }}>
                <Code block style={{ whiteSpace: 'pre' }}>
                  {lastResponse.yaml}
                </Code>
              </ScrollArea>
            )}
          </Stack>
        )}
        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed">
            Cmd/Ctrl+Enter to send
          </Text>
          <Group gap="xs">
            <Button variant="subtle" color="gray" onClick={onClose} disabled={pending}>
              Close
            </Button>
            <Button
              variant="filled"
              color="violet"
              leftSection={<Icon icon="material-symbols:auto-fix" width={14} />}
              onClick={() => void send()}
              disabled={!canSend}
              loading={pending}
            >
              {current ? 'Revise' : 'Fill'}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default AiFillModal;

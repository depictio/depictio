/**
 * Quick-prompt modal for adding a new dashboard component with AI.
 *
 * Surfaced from the editor's "Add component" menu as a sibling to the
 * manual stepper flow. The user picks a component type (chip strip) +
 * data collection (dropdown) + types a prompt; we call
 * /ai/component-from-prompt and hand the validated component dict back
 * to the host via `onApply` for hydration into the builder store.
 *
 * Auto-type inference ("just describe what you want") is intentionally
 * out-of-scope for v1 — the user explicitly picks the type, which keeps
 * the prompt context tight and avoids a separate inference endpoint.
 */

import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Chip,
  Group,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useComponentFromPrompt } from '../hooks';
import { useAISession } from '../store';
import type { ComponentType } from '../types';

/** One selectable DC entry — pulled from the dashboard's stored_metadata
 *  so we know both the DC id and the workflow id without an extra API
 *  round-trip. */
export interface AvailableDataCollection {
  dcId: string;
  dcTag: string;
  wfId?: string;
  wfTag?: string;
}

interface Props {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** Unique DCs already referenced anywhere on the dashboard — what the
   *  user can target without first attaching a new DC. The host is
   *  responsible for de-duplicating before passing in. */
  availableDataCollections: AvailableDataCollection[];
  /** Called with the validated component dict + the user-chosen type/dc
   *  /wf identifiers. The host typically stashes this for the create
   *  page to hydrate the builder store from on mount. */
  onApply: (
    parsed: Record<string, unknown>,
    componentType: ComponentType,
    dc: AvailableDataCollection,
  ) => void;
}

const TYPE_CHIPS: { type: ComponentType; label: string; icon: string }[] = [
  { type: 'figure', label: 'Figure', icon: 'mdi:graph-box' },
  { type: 'card', label: 'Card', icon: 'formkit:number' },
  { type: 'interactive', label: 'Filter', icon: 'bx:slider-alt' },
  { type: 'table', label: 'Table', icon: 'octicon:table-24' },
  { type: 'multiqc', label: 'MultiQC', icon: 'mdi:chart-line' },
  { type: 'image', label: 'Image', icon: 'mdi:image-area' },
  { type: 'map', label: 'Map', icon: 'mdi:map-marker-multiple' },
];

const AddWithAIModal: React.FC<Props> = ({
  opened,
  onClose,
  dashboardId,
  availableDataCollections,
  onApply,
}) => {
  const session = useAISession(dashboardId);
  const { run, pending, error } = useComponentFromPrompt(dashboardId);
  const [componentType, setComponentType] = useState<ComponentType>('figure');
  const [dcId, setDcId] = useState<string | null>(
    availableDataCollections[0]?.dcId ?? null,
  );
  const [prompt, setPrompt] = useState('');

  // Reset DC selection when the available list changes (e.g. a different
  // dashboard) so we don't carry a stale id over.
  React.useEffect(() => {
    if (!availableDataCollections.find((d) => d.dcId === dcId)) {
      setDcId(availableDataCollections[0]?.dcId ?? null);
    }
  }, [availableDataCollections, dcId]);

  const canSend = Boolean(
    prompt.trim() && session.llmKey && dcId && !pending,
  );

  async function send() {
    if (!canSend || !dcId) return;
    const dc = availableDataCollections.find((d) => d.dcId === dcId);
    if (!dc) return;
    try {
      const res = await run({
        data_collection_id: dcId,
        prompt: prompt.trim(),
        component_type: componentType,
        current: null,
      });
      onApply(res.parsed, componentType, dc);
      // Reset form for next round. Host typically closes the modal in
      // its onApply (via a navigate) — but if it stays open the user
      // gets a clean slate.
      setPrompt('');
    } catch {
      // useComponentFromPrompt surfaces the error via its `error` state.
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={
        <Group gap="xs">
          <Icon
            icon="material-symbols:auto-fix"
            width={18}
            color="var(--mantine-color-violet-6)"
          />
          <Text fw={600}>Add component with AI</Text>
          {session.model && (
            <Badge size="xs" variant="light" color="blue">
              {session.model.split('/').pop()}
            </Badge>
          )}
        </Group>
      }
    >
      <Stack gap="md">
        {!session.llmKey && (
          <Alert color="yellow" variant="light">
            Set an LLM API key from the dashboard settings drawer to use AI.
          </Alert>
        )}
        {availableDataCollections.length === 0 && (
          <Alert color="yellow" variant="light">
            This dashboard has no data collection yet — add a manual component
            first so the AI knows what data to author against.
          </Alert>
        )}

        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Component type
          </Text>
          <Chip.Group
            multiple={false}
            value={componentType}
            onChange={(v) => setComponentType(v as ComponentType)}
          >
            <Group gap="xs">
              {TYPE_CHIPS.map((c) => (
                <Chip key={c.type} value={c.type} size="sm" color="violet">
                  <Group gap={4} wrap="nowrap" align="center">
                    <Icon icon={c.icon} width={14} />
                    {c.label}
                  </Group>
                </Chip>
              ))}
            </Group>
          </Chip.Group>
        </Stack>

        <Select
          label="Data collection"
          placeholder="Pick a data collection"
          value={dcId}
          onChange={setDcId}
          data={availableDataCollections.map((d) => ({
            value: d.dcId,
            label: d.wfTag ? `${d.dcTag}  (${d.wfTag})` : d.dcTag,
          }))}
          disabled={availableDataCollections.length === 0}
          searchable
        />

        <Textarea
          label="Describe the component"
          placeholder='e.g. "Histogram of read length grouped by sample"'
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

        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed">
            Cmd/Ctrl+Enter to send
          </Text>
          <Group gap="xs">
            <Button variant="subtle" color="gray" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
            <Button
              variant="filled"
              color="violet"
              leftSection={<Icon icon="material-symbols:auto-fix" width={14} />}
              onClick={() => void send()}
              disabled={!canSend}
              loading={pending}
            >
              Generate
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default AddWithAIModal;

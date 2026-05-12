/**
 * JourneysSection — management UI inside the SettingsDrawer for cross-tab
 * journeys. Lists each journey with inline rename, pinned toggle, delete
 * journey, delete individual stops. Reordering stops is out of MVP scope
 * (the funnel widget shows stops in saved order; users can delete + re-add
 * to reorder for now).
 */

import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useGlobalFiltersStore } from '../stores/useGlobalFiltersStore';
import type { Journey } from 'depictio-react-core';

const JourneysSection: React.FC = () => {
  const journeys = useGlobalFiltersStore((s) => s.journeys);
  const upsertJourneyDef = useGlobalFiltersStore((s) => s.upsertJourneyDef);
  const removeJourney = useGlobalFiltersStore((s) => s.removeJourney);

  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (journeys.length === 0) {
    return (
      <Box>
        <Group gap={6} mb={4} align="center">
          <Icon icon="tabler:route" width={14} />
          <Text size="xs" tt="uppercase" c="dimmed" fw={600}>
            Journeys
          </Text>
        </Group>
        <Text size="sm" c="dimmed">
          No journeys yet. A journey is a multi-step path through your dashboard — set some
          filters, then click "Save as new journey" from the header menu or the funnel
          panel to start one.
        </Text>
      </Box>
    );
  }

  const startRename = (j: Journey) => {
    setRenameId(j.id);
    setRenameDraft(j.name);
  };
  const commitRename = async () => {
    if (!renameId) return;
    const target = journeys.find((j) => j.id === renameId);
    if (!target || !renameDraft.trim()) {
      setRenameId(null);
      return;
    }
    await upsertJourneyDef({ ...target, name: renameDraft.trim() });
    setRenameId(null);
  };
  const togglePinned = async (j: Journey) => {
    await upsertJourneyDef({ ...j, pinned: !j.pinned });
  };
  const deleteStop = async (j: Journey, stopId: string) => {
    await upsertJourneyDef({
      ...j,
      stops: j.stops.filter((s) => s.id !== stopId),
    });
  };
  const confirmDelete = async () => {
    if (!confirmDeleteId) return;
    await removeJourney(confirmDeleteId);
    setConfirmDeleteId(null);
  };

  return (
    <Box>
      <Group gap={6} mb={6} align="center">
        <Icon icon="tabler:route" width={14} />
        <Text size="xs" tt="uppercase" c="dimmed" fw={600}>
          Journeys ({journeys.length})
        </Text>
      </Group>
      <Stack gap="sm">
        {journeys.map((j) => (
          <Paper key={j.id} withBorder p="xs" radius="sm">
            <Group justify="space-between" wrap="nowrap" mb={4}>
              <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                <Icon
                  icon={j.icon ?? 'tabler:point'}
                  width={14}
                  color={j.color ?? undefined}
                />
                {renameId === j.id ? (
                  <TextInput
                    size="xs"
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void commitRename();
                      if (e.key === 'Escape') setRenameId(null);
                    }}
                    onBlur={() => void commitRename()}
                    autoFocus
                    style={{ flex: 1 }}
                  />
                ) : (
                  <Text size="sm" fw={600} truncate>
                    {j.name}
                  </Text>
                )}
                <Badge size="xs" variant="outline">
                  {j.stops.length} step{j.stops.length === 1 ? '' : 's'}
                </Badge>
              </Group>
              <Group gap={2} wrap="nowrap">
                <Tooltip label={j.pinned ? 'Unpin' : 'Pin to top'}>
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color={j.pinned ? 'blue' : 'gray'}
                    onClick={() => void togglePinned(j)}
                  >
                    <Icon icon={j.pinned ? 'tabler:pin-filled' : 'tabler:pin'} width={14} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Rename">
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color="gray"
                    onClick={() => startRename(j)}
                  >
                    <Icon icon="tabler:pencil" width={14} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Delete journey">
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color="red"
                    onClick={() => setConfirmDeleteId(j.id)}
                  >
                    <Icon icon="tabler:trash" width={14} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
            <Stack gap={2} pl={20}>
              {j.stops.map((s, idx) => (
                <Group key={s.id} gap={4} wrap="nowrap" justify="space-between">
                  <Text size="xs" c="dimmed" truncate>
                    {idx + 1}. {s.name}
                  </Text>
                  <Tooltip label="Remove step">
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="gray"
                      onClick={() => void deleteStop(j, s.id)}
                      disabled={j.stops.length === 1}
                    >
                      <Icon icon="tabler:x" width={12} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              ))}
            </Stack>
          </Paper>
        ))}
      </Stack>

      <Modal
        opened={confirmDeleteId !== null}
        onClose={() => setConfirmDeleteId(null)}
        title="Delete journey?"
        size="sm"
      >
        <Stack gap="sm">
          <Text size="sm">
            The journey and all of its stops will be removed. This affects every user of
            this dashboard.
          </Text>
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setConfirmDeleteId(null)}>
              Cancel
            </Button>
            <Button color="red" onClick={() => void confirmDelete()}>
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Box>
  );
};

export default JourneysSection;

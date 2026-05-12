/**
 * JourneyMenu — Header `rightExtras` entry point for the Journey feature.
 *
 * A small button (icon + label) that opens a Mantine `Menu` listing the
 * dashboard's journeys (pinned first, then by name). Top item is the
 * "+ Save current filters as new journey…" CTA. Bottom is "Manage journeys
 * →" which the host wires to opening the SettingsDrawer.
 *
 * Selecting a journey delegates to the host's `onSelect(journeyId)`, which
 * is responsible for calling the store's `setActiveJourney(...)` and
 * triggering navigation if the resolved stop's anchor tab differs from the
 * current tab.
 */

import React, { useState } from 'react';
import { Badge, Button, Group, Menu, Modal, Stack, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { Journey } from '../../api';

export interface JourneyMenuProps {
  journeys: Journey[];
  activeJourneyId: string | null;
  /** Activate a journey. Caller resolves which stop to land on (per-journey
   *  resume bookkeeping) + applies it. */
  onSelect: (journeyId: string) => void;
  /** User chose "Save current as new journey…" — opens a name prompt in
   *  this component, then calls the host with the chosen names. */
  onSaveAsNew: (args: { journeyName: string; stopName: string }) => void;
  /** Open the SettingsDrawer scrolled to the Journeys section. */
  onManage: () => void;
}

const JourneyMenu: React.FC<JourneyMenuProps> = ({
  journeys,
  activeJourneyId,
  onSelect,
  onSaveAsNew,
  onManage,
}) => {
  const [saveOpen, setSaveOpen] = useState(false);
  const [journeyName, setJourneyName] = useState('');
  const [stopName, setStopName] = useState('Starting point');

  const sorted = [...journeys].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  const activeName = journeys.find((j) => j.id === activeJourneyId)?.name ?? null;

  const handleSave = () => {
    if (!journeyName.trim() || !stopName.trim()) return;
    onSaveAsNew({ journeyName: journeyName.trim(), stopName: stopName.trim() });
    setSaveOpen(false);
    setJourneyName('');
    setStopName('Starting point');
  };

  return (
    <>
      <Menu shadow="md" position="bottom-end" width={300}>
        <Menu.Target>
          <Button
            variant={activeJourneyId ? 'light' : 'subtle'}
            color={activeJourneyId ? 'blue' : 'gray'}
            size="xs"
            leftSection={<Icon icon="tabler:route" width={14} />}
          >
            {activeName ? `Journey: ${activeName}` : 'Journeys'}
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            leftSection={<Icon icon="tabler:bookmark-plus" width={14} />}
            onClick={() => setSaveOpen(true)}
          >
            <Text size="sm" fw={600} c="blue.7">
              Save current filters as new journey…
            </Text>
          </Menu.Item>
          <Menu.Divider />
          {sorted.length === 0 ? (
            <Menu.Item disabled>
              <Text size="xs" c="dimmed">
                No journeys yet
              </Text>
            </Menu.Item>
          ) : (
            sorted.map((j) => {
              const isActive = j.id === activeJourneyId;
              return (
                <Menu.Item
                  key={j.id}
                  onClick={() => onSelect(j.id)}
                  leftSection={
                    <Icon
                      icon={isActive ? 'tabler:point-filled' : (j.icon ?? 'tabler:point')}
                      width={14}
                      color={
                        isActive
                          ? 'var(--mantine-color-blue-filled)'
                          : (j.color ?? undefined)
                      }
                    />
                  }
                  rightSection={
                    <Group gap={4} wrap="nowrap">
                      {j.pinned && (
                        <Icon
                          icon="tabler:pin"
                          width={12}
                          color="var(--mantine-color-dimmed)"
                        />
                      )}
                      <Badge size="xs" variant="outline">
                        {j.stops.length}
                      </Badge>
                    </Group>
                  }
                >
                  <Text size="sm" fw={isActive ? 700 : 500} truncate>
                    {j.name}
                  </Text>
                  {j.description && (
                    <Text size="xs" c="dimmed" truncate>
                      {j.description}
                    </Text>
                  )}
                </Menu.Item>
              );
            })
          )}
          <Menu.Divider />
          <Menu.Item
            leftSection={<Icon icon="tabler:settings" width={14} />}
            onClick={onManage}
          >
            <Text size="xs" c="dimmed">
              Manage journeys →
            </Text>
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>

      <Modal
        opened={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save current filters as new journey"
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            label="Journey name"
            placeholder="e.g. Riverwater funnel"
            value={journeyName}
            onChange={(e) => setJourneyName(e.currentTarget.value)}
            autoFocus
          />
          <TextInput
            label="First stop name"
            placeholder="e.g. All samples"
            value={stopName}
            onChange={(e) => setStopName(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setSaveOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!journeyName.trim() || !stopName.trim()}>
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default JourneyMenu;

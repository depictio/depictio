/**
 * "Add visualization" flow in a modal: depictio's component-type grid → its
 * per-type builder. On confirm the builder store is translated to a catalog
 * RenderSpec and handed back to the host — one path for every component type,
 * including advanced_viz, which used to be authored by a second panel with its
 * own state and its own idea of what a role binding looked like.
 */
import { useState } from 'react';
import { Modal, Group, Button, Title, Text, Stack, Divider } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import type { ComponentType } from 'depictio-builder/store/useBuilderStore';
import type { ParsedFixture, RenderSpec } from '../types';
import { getComponentTypeMeta } from 'depictio-builder/componentTypes';
import TypeGrid from './TypeGrid';
import DesignArea from './DesignArea';
import { seedBuilderStore } from './seedStore';
import { renderSpecFromStore } from '../catalog/fromBuilderStore';

export default function AddComponentModal({
  opened,
  onClose,
  fixture,
  onAdd,
}: {
  opened: boolean;
  onClose: () => void;
  fixture: ParsedFixture;
  onAdd: (spec: RenderSpec) => void;
}) {
  const [type, setType] = useState<ComponentType | null>(null);
  const [seeding, setSeeding] = useState(false);

  const reset = () => setType(null);

  const close = () => {
    reset();
    onClose();
  };

  const pick = async (t: ComponentType) => {
    setSeeding(true);
    try {
      await seedBuilderStore(fixture, t);
      setType(t);
    } finally {
      setSeeding(false);
    }
  };

  const confirm = () => {
    const spec = renderSpecFromStore();
    if (!spec) {
      notifications.show({ color: 'red', message: 'Complete the required bindings first.' });
      return;
    }
    onAdd(spec);
    notifications.show({ color: 'accent', message: 'Visualization added.' });
    close();
  };

  const meta = type ? getComponentTypeMeta(type) : null;

  return (
    <Modal
      opened={opened}
      onClose={close}
      size="90rem"
      // Fixed tall shell so the modal stays the SAME size across every option
      // (type grid, figure, card, table, interactive, advanced) — the design
      // surface scrolls internally instead of resizing the dialog.
      styles={{
        content: { height: '88vh' },
        body: { height: 'calc(88vh - 64px)', display: 'flex', flexDirection: 'column' },
      }}
      title={
        <Group gap="xs">
          <Icon icon="mdi:plus-box" width={20} />
          <Text fw={700}>{type ? `${meta?.label} design` : 'Add a visualization'}</Text>
        </Group>
      }
    >
      {!type ? (
        <Stack gap="sm" justify="center" style={{ flex: 1 }}>
          <Text size="sm" c="dimmed" ta="center">
            Choose a component type to bind to your fixture.
          </Text>
          <TypeGrid onPick={pick} />
          {seeding && (
            <Text size="xs" c="dimmed" ta="center">
              Loading builder…
            </Text>
          )}
        </Stack>
      ) : (
        <>
          <div style={{ textAlign: 'center', flexShrink: 0 }}>
            <Title order={4} fw={700}>
              {meta?.label}
            </Title>
            <Text size="sm" c="dimmed">
              {meta?.description}
            </Text>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', minHeight: 0, padding: '1rem 0' }}>
            <DesignArea type={type} />
          </div>
          <Divider />
          <Group justify="space-between" pt="sm" style={{ flexShrink: 0 }}>
            <Button variant="default" leftSection={<Icon icon="mdi:chevron-left" />} onClick={reset}>
              Change type
            </Button>
            <Button color="brand" leftSection={<Icon icon="mdi:plus" />} onClick={confirm}>
              Add to output
            </Button>
          </Group>
        </>
      )}
    </Modal>
  );
}

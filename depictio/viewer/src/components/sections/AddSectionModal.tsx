/**
 * Add-only entry point for sections, opened from the header's Add menu.
 *
 * Creation lives here so the Add menu stays a pure add surface; editing,
 * reordering and deleting live in the Sections manager (`SectionsModal`),
 * reached from the "…" action on each section header. Same modal chrome and
 * the same grid/filter tab split as the manager, so the two read as one UI.
 */
import React from 'react';
import { Modal, Stack, Tabs, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import SectionForm from './SectionForm';
import type { SectionKind, SectionOp } from './sectionMutations';
import { sectionsFor } from './sectionMutations';

export interface AddSectionModalProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  onOp: (op: SectionOp) => void;
}

const AddSectionModal: React.FC<AddSectionModalProps> = ({
  opened,
  onClose,
  dashboard,
  onOp,
}) => {
  const takenFor = (kind: SectionKind) =>
    dashboard ? sectionsFor(dashboard, kind).map((s) => s.name.toLowerCase()) : [];

  const submit = (kind: SectionKind) => (spec: FilterSectionSpec) => {
    onOp({ op: 'create', kind, spec });
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Add section"
      centered
      size="lg"
      radius="md"
      overlayProps={{ blur: 2 }}
    >
      {!dashboard ? (
        <Text size="sm" c="dimmed">
          Loading…
        </Text>
      ) : (
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Sections group components under a collapsible header. The filter panel and
            the dashboard grid keep separate lists, so pick where this one lives.
          </Text>
          <Tabs defaultValue="grid" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="grid" leftSection={<Icon icon="mdi:view-grid-outline" width={14} />}>
                Dashboard grid
              </Tabs.Tab>
              <Tabs.Tab
                value="filter"
                leftSection={<Icon icon="mdi:filter-variant" width={14} />}
              >
                Filter panel
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="grid" pt="md">
              <SectionForm
                initial={null}
                taken={takenFor('grid')}
                onCancel={onClose}
                onSubmit={submit('grid')}
              />
            </Tabs.Panel>
            <Tabs.Panel value="filter" pt="md">
              <SectionForm
                initial={null}
                taken={takenFor('filter')}
                onCancel={onClose}
                onSubmit={submit('filter')}
              />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
    </Modal>
  );
};

export default AddSectionModal;

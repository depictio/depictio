/**
 * Authoring UI for a dashboard's sections.
 *
 * Two tabs rather than one list, because `filter_sections` and `grid_sections`
 * are independent namespaces that may use the same name for different things.
 * Presenting them as one list would make renaming "QC" look like it should
 * affect both.
 *
 * Holds no dashboard state: it emits intents and `EditorApp` reduces them
 * against the live dashboard ref, so a section change and a concurrent layout
 * drag can't overwrite each other.
 */
import React, { useEffect } from 'react';
import { Modal, Stack, Tabs, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardData } from 'depictio-react-core';

import SectionList from './SectionList';
import type { SectionOp } from './sectionMutations';
import { sectionsFor } from './sectionMutations';

export interface SectionsModalProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  onOp: (op: SectionOp) => void;
}

const SectionsModal: React.FC<SectionsModalProps> = ({
  opened,
  onClose,
  dashboard,
  onOp,
}) => {
  // Sections a component names but the dashboard never declared are invisible to
  // the manager until they exist as specs. Writing them out on open is what lets
  // a YAML-authored or free-text section be given an icon and a colour, and it
  // is a no-op for rendering: the derived order already puts declared sections
  // first and undeclared ones after, in the same first-appearance order.
  useEffect(() => {
    if (!opened || !dashboard) return;
    onOp({ op: 'materialize', kind: 'filter' });
    onOp({ op: 'materialize', kind: 'grid' });
    // Deliberately keyed on `opened` alone: re-running as the dashboard changes
    // under an open modal would fight the user's own edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Sections"
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
            the dashboard grid keep separate lists, so the same name can mean a
            different section in each.
          </Text>
          <Tabs defaultValue="grid" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="grid" leftSection={<Icon icon="mdi:view-grid-outline" width={14} />}>
                Dashboard grid ({sectionsFor(dashboard, 'grid').length})
              </Tabs.Tab>
              <Tabs.Tab
                value="filter"
                leftSection={<Icon icon="mdi:filter-variant" width={14} />}
              >
                Filter panel ({sectionsFor(dashboard, 'filter').length})
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="grid" pt="md">
              <SectionList kind="grid" dashboard={dashboard} onOp={onOp} />
            </Tabs.Panel>
            <Tabs.Panel value="filter" pt="md">
              <SectionList kind="filter" dashboard={dashboard} onOp={onOp} />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
    </Modal>
  );
};

export default SectionsModal;

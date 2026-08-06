import React, { useMemo } from 'react';
import { ActionIcon, Group, ScrollArea, Stack, Tabs, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { DataGridBody, MetadataBody } from 'depictio-react-core';
import type { DashboardData, DashboardPermissions, StoredMetadata } from 'depictio-react-core';
import DashboardInfoBody from '../DashboardInfoBody';
import { useNotesEditor } from '../../components/notes/useNotesEditor';
import NotesEditorSurface, {
  NotesSaveStatusIndicator,
} from '../../components/notes/NotesEditorSurface';
import { useUiStore } from '../../store/useUiStore';
import type { InspectorTab } from '../../store/useUiStore';

/** Width of `AppShell.Aside`; also the swing fed to the panel-toggle event. */
export const INSPECTOR_WIDTH = 340;

interface InspectorProps {
  dashboard: DashboardData | null;
  dashboardId: string | null;
}

/**
 * Docked right-hand panel showing the selected component's details.
 *
 * Replaces a set of floating surfaces — the metadata popover, the settings
 * drawer, the notes footer — with one panel that stays put. Each tab renders
 * the same body component its popover does, so the two can't drift; the
 * popovers stay in place as the fallback whenever the feature is off.
 *
 * Notes are the exception: their editor runs a debounced autosave, so exactly
 * one surface may mount it. The app drops `NotesFooter` when the inspector is
 * enabled.
 */
const Inspector: React.FC<InspectorProps> = ({ dashboard, dashboardId }) => {
  const selectedComponentId = useUiStore((s) => s.selectedComponentId);
  const inspectorTab = useUiStore((s) => s.inspectorTab);
  const setInspectorTab = useUiStore((s) => s.setInspectorTab);
  const closeInspector = useUiStore((s) => s.closeInspector);

  const metadataList = (dashboard?.stored_metadata as StoredMetadata[] | undefined) ?? [];
  const selected = useMemo(
    () =>
      selectedComponentId
        ? metadataList.find((m) => m.index === selectedComponentId) ?? null
        : null,
    [metadataList, selectedComponentId],
  );

  // Published by the selected component's renderer, when it is an advanced-viz
  // one. Absent for every other component type, which is why both tabs are
  // conditional rather than empty.
  const extras = useUiStore((s) =>
    selectedComponentId ? s.advancedVizExtras[selectedComponentId] ?? null : null,
  );

  const notes = useNotesEditor(
    dashboardId ?? '',
    (dashboard?.notes_content as string) ?? '',
    dashboard?.permissions as DashboardPermissions | undefined,
  );

  // Selecting a plain figure while the Controls tab is active would otherwise
  // leave the panel on a tab that no longer exists, showing an empty body.
  const activeTab: InspectorTab =
    (inspectorTab === 'controls' && !extras?.controls) ||
    (inspectorTab === 'data' && !extras?.data)
      ? 'info'
      : inspectorTab;

  const title = selected
    ? (selected.title as string | undefined) || (selected.component_type as string) || 'Component'
    : 'Dashboard';

  return (
    <Stack gap={0} h="100%">
      <Group justify="space-between" wrap="nowrap" px="sm" py="xs">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Inspector
          </Text>
          <Text size="sm" fw={600} truncate>
            {title}
          </Text>
        </Stack>
        <Tooltip label="Close inspector" withArrow>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={closeInspector}
            aria-label="Close inspector"
          >
            <Icon icon="mdi:close" width={16} />
          </ActionIcon>
        </Tooltip>
      </Group>

      <Tabs
        value={activeTab}
        onChange={(value) => value && setInspectorTab(value as InspectorTab)}
        // Panels stay mounted (Mantine's default): unmounting the Notes panel
        // would tear down TipTap's DOM view on every tab switch. The Info
        // tab's project fetch is gated on `active` instead.
        style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
      >
        <Tabs.List grow>
          {extras?.controls && (
            <Tabs.Tab
              value="controls"
              leftSection={<Icon icon="tabler:adjustments-horizontal" width={14} />}
            >
              Controls
            </Tabs.Tab>
          )}
          {extras?.data && (
            <Tabs.Tab value="data" leftSection={<Icon icon="tabler:table" width={14} />}>
              Data
            </Tabs.Tab>
          )}
          <Tabs.Tab value="info" leftSection={<Icon icon="mdi:information-outline" width={14} />}>
            Info
          </Tabs.Tab>
          <Tabs.Tab value="notes" leftSection={<Icon icon="material-symbols:edit-note" width={14} />}>
            Notes
          </Tabs.Tab>
        </Tabs.List>

        {/* The same JSX the settings popover shows, minus the popover — which
            also drops the reason that popover needs `closeOnClickOutside`:
            portalled Mantine Selects have nothing left to close. */}
        {extras?.controls && (
          <Tabs.Panel value="controls" style={{ flex: 1, minHeight: 0 }}>
            <ScrollArea h="100%" type="auto" px="sm" py="xs">
              {extras.controls}
            </ScrollArea>
          </Tabs.Panel>
        )}

        {extras?.data && (
          <Tabs.Panel
            value="data"
            // Unmounted while inactive, unlike the other panels: the grid
            // transposes up to 100k rows column→row on mount, which is not work
            // to do for a tab nobody is looking at. Notes can't do this — it
            // would tear down TipTap's DOM view.
            keepMounted={false}
            style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
            px="sm"
            py="xs"
          >
            <DataGridBody
              dataRows={extras.data.rows}
              dataColumns={extras.data.columns}
              tierAnnotation={extras.data.tierAnnotation}
              height="100%"
            />
          </Tabs.Panel>
        )}

        {/* Info: the selected component's metadata, or the dashboard's own
            fields when nothing is selected — which is what makes this tab a
            replacement for the settings drawer rather than an addition. */}
        <Tabs.Panel value="info" style={{ flex: 1, minHeight: 0 }}>
          <ScrollArea h="100%" type="auto" px="sm" py="xs">
            {selected ? (
              <MetadataBody metadata={selected} />
            ) : (
              <DashboardInfoBody dashboard={dashboard} active={activeTab === 'info'} />
            )}
          </ScrollArea>
        </Tabs.Panel>

        <Tabs.Panel
          value="notes"
          style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
        >
          <Group px="sm" py={4} justify="flex-end">
            <NotesSaveStatusIndicator
              status={notes.status}
              savedAt={notes.savedAt}
              canEdit={notes.canEdit}
            />
          </Group>
          <NotesEditorSurface editor={notes.editor} canEdit={notes.canEdit} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
};

export default Inspector;

import React, { useEffect, useState } from 'react';
import {
  Button,
  Group,
  Modal,
  Select,
  Stack,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary } from 'depictio-react-core';

/** Mirrors the icon-color options in Dash's tab modal (`tab_modal.py:206-362`).
 *  "Auto" leaves the field empty so the parent's auto-resolution kicks in. */
const COLOR_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Auto' },
  { value: 'gray', label: 'Gray' },
  { value: 'red', label: 'Red' },
  { value: 'pink', label: 'Pink' },
  { value: 'grape', label: 'Grape' },
  { value: 'violet', label: 'Violet' },
  { value: 'indigo', label: 'Indigo' },
  { value: 'blue', label: 'Blue' },
  { value: 'cyan', label: 'Cyan' },
  { value: 'teal', label: 'Teal' },
  { value: 'green', label: 'Green' },
  { value: 'lime', label: 'Lime' },
  { value: 'yellow', label: 'Yellow' },
  { value: 'orange', label: 'Orange' },
  { value: 'dark', label: 'Dark' },
];

export type TabModalMode = 'create' | 'edit';

export interface TabModalSubmitPayload {
  title: string;
  tab_icon?: string;
  tab_icon_color?: string;
  /** Only present when editing a main tab. */
  main_tab_name?: string;
}

interface TabModalProps {
  opened: boolean;
  mode: TabModalMode;
  /** Required in edit mode — pre-populates the form. Ignored in create mode. */
  tab?: DashboardSummary | null;
  onClose: () => void;
  onSubmit: (payload: TabModalSubmitPayload) => Promise<void> | void;
  /** True while the parent's submit handler is in flight. Disables actions. */
  submitting?: boolean;
}

/**
 * Modal for creating or editing a tab.
 *
 * Field set mirrors `depictio/dash/layouts/tab_modal.py` (lines 206-362):
 *   - Tab name (required)
 *   - Main tab name (only when editing a main tab)
 *   - Icon — Iconify name (e.g. `mdi:chart-bar`); live preview to the right
 *   - Color — Mantine palette + "Auto"
 *
 * Icon picker is intentionally simpler than Dash's preset gallery: a free-text
 * Iconify name + preview is sufficient for the common "I want a different
 * icon" flow without dragging in a 16-icon table.
 */
const TabModal: React.FC<TabModalProps> = ({
  opened,
  mode,
  tab,
  onClose,
  onSubmit,
  submitting = false,
}) => {
  const isMainTab = mode === 'edit' && tab && !tab.parent_dashboard_id;

  const [title, setTitle] = useState('');
  const [mainTabName, setMainTabName] = useState('');
  const [tabIcon, setTabIcon] = useState('');
  const [tabIconColor, setTabIconColor] = useState('');

  // Reset / pre-populate fields whenever the modal opens (or the target tab
  // changes). We watch `opened` specifically so closing-then-reopening with
  // the same target still re-syncs from props.
  useEffect(() => {
    if (!opened) return;
    if (mode === 'edit' && tab) {
      setTitle(tab.title || '');
      setMainTabName(tab.main_tab_name || '');
      setTabIcon(tab.tab_icon || tab.icon || '');
      setTabIconColor(tab.tab_icon_color || tab.icon_color || '');
    } else {
      setTitle('');
      setMainTabName('');
      setTabIcon('');
      setTabIconColor('');
    }
  }, [opened, mode, tab]);

  const handleSubmit = async () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;

    const payload: TabModalSubmitPayload = {
      title: trimmedTitle,
      tab_icon: tabIcon.trim() || undefined,
      tab_icon_color: tabIconColor || undefined,
    };
    if (isMainTab) {
      payload.main_tab_name = mainTabName.trim() || undefined;
    }
    await onSubmit(payload);
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={mode === 'create' ? 'Add tab' : 'Edit tab'}
      size="md"
      centered
    >
      <Stack gap="sm">
        <TextInput
          label="Tab name"
          placeholder="Variants"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
          required
          data-autofocus
        />

        {isMainTab && (
          <TextInput
            label="Main tab label"
            description="Short label shown in the sidebar pill (defaults to tab name)."
            placeholder="MultiQC"
            value={mainTabName}
            onChange={(e) => setMainTabName(e.currentTarget.value)}
          />
        )}

        <Group align="flex-end" gap="xs" wrap="nowrap">
          <TextInput
            label="Icon"
            description="Iconify name, e.g. mdi:chart-bar"
            placeholder="mdi:chart-bar"
            value={tabIcon}
            onChange={(e) => setTabIcon(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <div
            style={{
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 4,
              border: '1px solid var(--mantine-color-default-border)',
              flexShrink: 0,
              marginBottom: 4,
            }}
            aria-label="Icon preview"
          >
            {tabIcon.trim() ? (
              <Icon icon={tabIcon.trim()} width={20} />
            ) : (
              <Icon icon="mdi:tab" width={20} style={{ opacity: 0.3 }} />
            )}
          </div>
        </Group>

        <Select
          label="Icon color"
          data={COLOR_OPTIONS}
          value={tabIconColor}
          onChange={(v) => setTabIconColor(v ?? '')}
          allowDeselect={false}
        />

        <Group justify="flex-end" gap="xs" mt="sm">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            loading={submitting}
            disabled={!title.trim()}
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default TabModal;

import React, { useEffect, useState } from 'react';
import {
  Anchor,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary } from 'depictio-react-core';

/** True for path-like icon values (asset URLs such as
 *  `/assets/images/icons/favicon.png`) rather than Iconify names. Mirrors the
 *  same check in `chrome/Sidebar.tsx` / `chrome/Header.tsx`. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** Material Design Icons (`mdi:`) browser — prefix any icon name shown there
 *  with `mdi:` to use it here. Same target as the dashboard create/edit
 *  modals for consistency. */
const MDI_BROWSER_URL = 'https://pictogrammers.com/library/mdi/';

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

  // Live preview matching how the sidebar/header render the icon:
  //   - image path (asset URL)  → <img> (Iconify can't load file paths)
  //   - Iconify name            → <Icon> tinted with the selected color
  //     (empty color = neutral preview, mirroring "Auto")
  const trimmedIcon = tabIcon.trim();
  const previewColor = tabIconColor
    ? `var(--mantine-color-${tabIconColor}-6)`
    : undefined;
  const previewIcon = !trimmedIcon ? (
    <Icon icon="mdi:tab" width={20} style={{ opacity: 0.3 }} />
  ) : isImagePath(trimmedIcon) ? (
    <img
      src={trimmedIcon}
      alt=""
      style={{ maxWidth: 20, maxHeight: 20, objectFit: 'contain' }}
    />
  ) : (
    <Icon icon={trimmedIcon} width={20} style={{ color: previewColor }} />
  );

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      withCloseButton
      size="md"
      centered
    >
      <Stack gap="sm">
        {/* Header — consistent with the dashboard create/edit modals:
            centered orange icon + title. */}
        <Group justify="center" gap="sm" mb="xs">
          <Icon
            icon={mode === 'create' ? 'mdi:tab-plus' : 'mdi:square-edit-outline'}
            width={28}
            height={28}
            color="var(--mantine-color-orange-6)"
          />
          <Title order={3} c="orange" m={0}>
            {mode === 'create' ? 'Add Tab' : 'Edit Tab'}
          </Title>
        </Group>

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
            description={
              <>
                Iconify name, e.g. mdi:chart-bar —{' '}
                <Anchor
                  href={MDI_BROWSER_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  inherit
                >
                  browse icons
                </Anchor>
              </>
            }
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
            {previewIcon}
          </div>
        </Group>

        <Select
          label="Icon color"
          data={COLOR_OPTIONS}
          value={tabIconColor}
          onChange={(v) => setTabIconColor(v ?? '')}
          allowDeselect={false}
        />

        <Group justify="flex-end" gap="md" mt="sm">
          <Button
            variant="outline"
            color="gray"
            radius="md"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            color="orange"
            radius="md"
            leftSection={
              <Icon
                icon={mode === 'create' ? 'mdi:plus' : 'mdi:content-save'}
                width={16}
              />
            }
            onClick={handleSubmit}
            loading={submitting}
            disabled={!title.trim()}
          >
            {mode === 'create' ? 'Add Tab' : 'Save Changes'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default TabModal;

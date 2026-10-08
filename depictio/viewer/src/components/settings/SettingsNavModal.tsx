/**
 * A settings dialog laid out like GitHub's or VS Code's settings: a rail of
 * sections on the left and the active one as a page on the right, in a wide
 * modal that goes full screen on a phone, where the rail becomes a select.
 *
 * Shared by the dashboard settings (`chrome/SettingsDrawer.tsx`) and the
 * project settings (`projects/detail/ProjectSettingsModal.tsx`), so both read
 * as the same kind of thing. The section a reader last opened is remembered
 * per browser under a caller-chosen key.
 *
 * - `SettingsNavModal` is the whole dialog: the frame plus the layout.
 * - `SettingsRailNote` is a one-line note for the bottom of the rail (how the
 *   dialog saves, for instance).
 */
import React from 'react';
import { Box, Divider, Group, Modal, NavLink, ScrollArea, Select, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from 'depictio-react-core';

/** A bare glyph in the (dashboard's) primary colour, the way the chrome draws
 *  its icons elsewhere (`SectionIcon`, the sidebar): a tinted square read as a
 *  button in a row that already carries a chevron. */
export const SECTION_ICON_STYLE: React.CSSProperties = {
  color: 'var(--mantine-primary-color-filled)',
  flexShrink: 0,
};

/** One section of the dialog: an entry in the rail and the page it opens. */
export interface SettingsNavSection {
  key: string;
  icon: string;
  title: string;
  /** Shorter name for the nav rail, when the title would wrap there. */
  navLabel?: string;
  /** Something to show at the end of the section's rail entry while the
   *  reader is elsewhere, such as a spinner for work still running there. */
  navHint?: React.ReactNode;
  /** What the section is for and who it affects. */
  subtitle: string;
  body: React.ReactNode;
}

/** Below this the rail no longer fits beside the page and becomes a select. */
const NARROW_QUERY = '(max-width: 640px)';

const RAIL_WIDTH = 220;

function readActive(storageKey: string): string | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed === 'string') return parsed;
    }
  } catch {
    // Storage blocked or corrupt: the caller falls back to its default.
  }
  return null;
}

function writeActive(storageKey: string, value: string) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Remembering a layout detail is a convenience; ignore failures.
  }
}

/** A one-line note at the bottom of the rail, such as how the dialog saves. */
export const SettingsRailNote: React.FC<{ icon: string; children: React.ReactNode }> = ({
  icon,
  children,
}) => (
  <Group gap={6} wrap="nowrap" px={6} pt="sm">
    <Icon icon={icon} width={14} style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }} />
    <Text size="xs" c="dimmed" lh={1.3}>
      {children}
    </Text>
  </Group>
);

interface SettingsNavLayoutProps {
  sections: SettingsNavSection[];
  /** localStorage key under which the last opened section is remembered. */
  storageKey: string;
  /** The section to open on before the reader has picked one. */
  defaultSection?: string;
  /** Open on this section rather than the remembered one. Read once: the
   *  modal remounts its body on every open. */
  initialSection?: string;
  /** Pinned to the bottom of the rail (wide layout only). */
  footer?: React.ReactNode;
  /** Names the rail and the narrow-screen select for assistive tech. */
  ariaLabel: string;
  testIdPrefix: string;
}

const SettingsNavLayout: React.FC<SettingsNavLayoutProps> = ({
  sections,
  storageKey,
  defaultSection,
  initialSection,
  footer,
  ariaLabel,
  testIdPrefix,
}) => {
  const [stored, setStored] = React.useState<string | null>(
    () => initialSection ?? readActive(storageKey),
  );
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });

  // A remembered section can be missing today (no feedback link configured,
  // or an editor-only one in the viewer): fall back rather than draw nothing.
  const active =
    sections.find((s) => s.key === stored) ??
    sections.find((s) => s.key === defaultSection) ??
    sections[0];
  const select = (key: string) => {
    setStored(key);
    writeActive(storageKey, key);
  };

  const page = active && (
    <Stack gap="lg" data-testid={`${testIdPrefix}-section-${active.key}`}>
      {narrow ? (
        // The select above already names the section; repeating it as a
        // heading on a phone only pushes the fields down.
        <Text size="sm" c="dimmed">
          {active.subtitle}
        </Text>
      ) : (
        <Stack gap={2}>
          <Group gap="sm" wrap="nowrap">
            <Icon icon={active.icon} width={22} height={22} style={SECTION_ICON_STYLE} />
            <Text fw={600} size="lg" lh={1.25}>
              {active.title}
            </Text>
          </Group>
          <Text size="sm" c="dimmed">
            {active.subtitle}
          </Text>
        </Stack>
      )}
      <Divider />
      {active.body}
    </Stack>
  );

  if (narrow) {
    return (
      <Stack gap="md">
        <Select
          aria-label={`${ariaLabel} section`}
          value={active?.key ?? null}
          onChange={(value) => value && select(value)}
          data={sections.map((s) => ({ value: s.key, label: s.title }))}
          allowDeselect={false}
          comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
          leftSection={
            active ? <Icon icon={active.icon} width={16} style={SECTION_ICON_STYLE} /> : null
          }
          data-testid={`${testIdPrefix}-nav-select`}
        />
        {page}
      </Stack>
    );
  }

  return (
    <Group
      align="stretch"
      gap={0}
      wrap="nowrap"
      // A fixed height, so moving between a short and a long section doesn't
      // make the dialog jump.
      h="min(640px, calc(100dvh - 140px))"
    >
      <Stack
        w={RAIL_WIDTH}
        gap={0}
        justify="space-between"
        p="sm"
        style={{
          flexShrink: 0,
          borderRight: '1px solid var(--mantine-color-default-border)',
          background: 'var(--mantine-color-default-hover)',
        }}
      >
        <Stack gap={2} component="nav" aria-label={`${ariaLabel} sections`}>
          {sections.map((s) => {
            const isActive = s.key === active?.key;
            return (
              <NavLink
                key={s.key}
                label={s.navLabel ?? s.title}
                active={isActive}
                variant="light"
                onClick={() => select(s.key)}
                leftSection={
                  <Icon
                    icon={s.icon}
                    width={18}
                    height={18}
                    style={{
                      flexShrink: 0,
                      color: isActive
                        ? 'var(--mantine-primary-color-filled)'
                        : 'var(--mantine-color-dimmed)',
                    }}
                  />
                }
                rightSection={s.navHint}
                styles={{
                  root: { borderRadius: 'var(--mantine-radius-sm)' },
                  label: { fontWeight: isActive ? 600 : 500 },
                }}
                data-testid={`${testIdPrefix}-nav-${s.key}`}
              />
            );
          })}
        </Stack>
        {footer}
      </Stack>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Box px="xl" py="lg" maw={620}>
          {page}
        </Box>
      </ScrollArea>
    </Group>
  );
};

export interface SettingsNavModalProps
  extends Omit<SettingsNavLayoutProps, 'ariaLabel' | 'testIdPrefix'> {
  opened: boolean;
  onClose: () => void;
  title: React.ReactNode;
  /** Names the rail and the narrow-screen select ("<label> sections"). */
  ariaLabel?: string;
  /** Prefix of the test ids: `<prefix>-modal`, `<prefix>-nav-<key>`,
   *  `<prefix>-nav-select` and `<prefix>-section-<key>`. */
  testIdPrefix?: string;
  /** Passed to the Modal root last, e.g. a brand scope's `className` and
   *  `data-mantine-color-scheme`, or a `zIndex`. */
  modalProps?: Record<string, unknown>;
}

/**
 * The settings dialog: a wide modal, full screen on a phone, with no body
 * padding so the rail runs edge to edge, around the rail-and-page layout.
 * Opens above the floating map card (`Z_LAYERS.overlay`), so its overlay dims
 * it like the rest of the page instead of leaving it lit on top.
 */
export const SettingsNavModal: React.FC<SettingsNavModalProps> = ({
  opened,
  onClose,
  title,
  ariaLabel = 'Settings',
  testIdPrefix = 'settings',
  modalProps,
  ...layout
}) => {
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      size={860}
      fullScreen={narrow}
      radius="md"
      centered
      zIndex={Z_LAYERS.overlay}
      data-testid={`${testIdPrefix}-modal`}
      styles={{
        header: { borderBottom: '1px solid var(--mantine-color-default-border)' },
        body: narrow ? { paddingTop: 'var(--mantine-spacing-md)' } : { padding: 0 },
      }}
      {...modalProps}
    >
      <SettingsNavLayout {...layout} ariaLabel={ariaLabel} testIdPrefix={testIdPrefix} />
    </Modal>
  );
};

export default SettingsNavModal;

/**
 * One row in the version history (the settings' History section).
 *
 * One line per version, so the list scans like a timeline: the kind as an
 * icon, the title, how long ago, and only the badges worth reading at a glance.
 * Everything else (exact date, author, counts, data coverage) folds into a
 * details area under the line, closed by default.
 *
 * Deliberately inert on click: selecting a version must never write anything.
 * Clicking the line only folds its details open or shut. Every action is an
 * explicit control: Restore inline, as the primary one, and the rest in the
 * row's menu. The two irreversible ones (restore, delete) route through a
 * confirm dialog owned by the panel.
 *
 * The row says what kind of save it was in words (the icon's label, and a
 * badge in the details), not only through the icon's colour, and an action
 * that is not available stays visible with the reason rather than
 * disappearing.
 */

import React, { useId, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Collapse,
  Divider,
  Group,
  Menu,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  rem,
  type MantineColor,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  useBrandScopeAttributes,
  Z_LAYERS,
  type DashboardVersionSummary,
} from 'depictio-react-core';

import {
  absDateTime,
  absTime,
  dataCoverageLabel,
  isoDateTime,
  kindMeta,
  relTime,
  saveSpanLabel,
  versionTitle,
} from './format';

interface VersionTimelineItemProps {
  version: DashboardVersionSummary;
  /** This version matches the live dashboard, so restoring it is a no-op. */
  isCurrent: boolean;
  /** This version's data is what the editor is drawing from (Data version). */
  dataActive?: boolean;
  /** Draw a rule above the row: every row of a day group but its first. */
  withDivider?: boolean;
  /** Owner-level rights: delete. Erasing history is the one action a restore
   *  cannot undo, so the server gates it harder than the rest. */
  canDelete: boolean;
  /** An action is in flight: every row's actions wait for it. */
  busy: boolean;
  onPreview: (version: DashboardVersionSummary) => void;
  /** Bookmark (pin and name) the version, or edit / remove its bookmark. */
  onBookmark: (version: DashboardVersionSummary) => void;
  onRestore: (version: DashboardVersionSummary) => void;
  onDelete: (version: DashboardVersionSummary) => void;
}

/** The kind icon's size, in px. The details are indented by it plus the gap
 *  after it, so they line up under the title rather than under the icon. */
const KIND_ICON_SIZE = 22;
const DETAILS_INDENT = `calc(${rem(KIND_ICON_SIZE)} + var(--mantine-spacing-xs))`;

/**
 * An icon-only row action. `unavailable` keeps it visible but inert, with the
 * reason as its tooltip: `data-disabled` rather than `disabled`, because a
 * disabled button fires no pointer events and so could never show why.
 */
const RowAction: React.FC<{
  label: string;
  icon: string;
  testId: string;
  onClick: () => void;
  unavailable?: string | null;
  busy: boolean;
  color?: MantineColor;
}> = ({ label, icon, testId, onClick, unavailable, busy, color = 'gray' }) => (
  <Tooltip label={unavailable ?? label} withArrow zIndex={Z_LAYERS.tooltip}>
    <ActionIcon
      variant="subtle"
      color={color}
      size="md"
      aria-label={label}
      aria-disabled={unavailable ? true : undefined}
      data-disabled={unavailable ? true : undefined}
      disabled={busy}
      onClick={(event) => {
        if (unavailable) {
          event.preventDefault();
          return;
        }
        onClick();
      }}
      data-testid={testId}
    >
      <Icon icon={icon} width={16} />
    </ActionIcon>
  </Tooltip>
);

const VersionTimelineItem: React.FC<VersionTimelineItemProps> = ({
  version,
  isCurrent,
  dataActive = false,
  withDivider = false,
  canDelete,
  busy,
  onPreview,
  onBookmark,
  onRestore,
  onDelete,
}) => {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  // The menu is portaled to <body>, outside the dashboard's brand scope.
  const brandScope = useBrandScopeAttributes();

  const meta = kindMeta(version.kind);
  const title = versionTitle(version);
  const span = saveSpanLabel(version);
  const coverage = dataCoverageLabel(version.data_version_kinds || {});
  // A bookmark takes over the icon, so its label has to keep the kind.
  const kindLabel = version.pinned ? `${meta.label}, bookmarked` : meta.label;
  const deleteBlocked = canDelete ? null : "Only the dashboard's owners can delete a version";
  const toggle = () => setExpanded((open) => !open);

  return (
    <Box
      role="listitem"
      aria-current={isCurrent ? 'true' : undefined}
      data-testid="version-row"
      data-version-seq={version.seq}
      data-version-kind={version.kind}
    >
      {withDivider && <Divider aria-hidden />}

      <Group gap="xs" wrap="nowrap" py={6}>
        {/* Clicking the line folds the details, as the chevron does. A pointer
            shortcut only, so it stays out of the tab order: the chevron is the
            control keyboards and screen readers get. */}
        <Group
          gap="xs"
          wrap="nowrap"
          onClick={toggle}
          style={{ flex: 1, minWidth: 0, cursor: 'pointer' }}
        >
          {/* A bookmark is the strongest signal in the list, so it wins the
              icon. Its shape and label carry the kind, never its colour alone. */}
          <Tooltip label={kindLabel} withArrow zIndex={Z_LAYERS.tooltip}>
            <ThemeIcon
              variant="light"
              color={version.pinned ? 'yellow' : meta.color}
              size={KIND_ICON_SIZE}
              radius="xl"
              role="img"
              aria-label={kindLabel}
            >
              <Icon icon={version.pinned ? 'mdi:bookmark' : meta.icon} width={12} aria-hidden />
            </ThemeIcon>
          </Tooltip>

          <Group gap={6} wrap="wrap" style={{ flex: 1, minWidth: 0, rowGap: 2 }}>
            <Text
              size="sm"
              fw={version.pinned || version.label ? 600 : 500}
              truncate
              style={{ minWidth: 0, maxWidth: '100%' }}
            >
              {title}
            </Text>
            {isCurrent && (
              <Badge size="xs" variant="filled" color="teal">
                Current
              </Badge>
            )}
            {version.pinned && (
              <Badge size="xs" variant="light" color="yellow">
                Bookmarked
              </Badge>
            )}
            {dataActive && (
              <Badge size="xs" variant="outline" color="yellow">
                Data in use
              </Badge>
            )}
          </Group>

          <Tooltip label={absTime(version.created_at)} withArrow zIndex={Z_LAYERS.tooltip}>
            <Text
              component="time"
              dateTime={isoDateTime(version.created_at)}
              size="xs"
              c="dimmed"
              style={{ flexShrink: 0, whiteSpace: 'nowrap' }}
            >
              {relTime(version.created_at)}
            </Text>
          </Tooltip>
        </Group>

        <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
          <RowAction
            label={`Restore ${title}`}
            icon="mdi:backup-restore"
            testId="version-restore"
            busy={busy}
            unavailable={isCurrent ? 'This is the current state' : null}
            onClick={() => onRestore(version)}
          />

          <Menu
            position="bottom-end"
            withinPortal
            shadow="md"
            width={240}
            zIndex={Z_LAYERS.tooltip}
          >
            <Menu.Target>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="md"
                aria-label={`More actions for ${title}`}
                disabled={busy}
                data-testid="version-actions"
              >
                <Icon icon="mdi:dots-vertical" width={16} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown
              className={brandScope?.className}
              data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
              data-testid="version-actions-menu"
            >
              <Menu.Item
                leftSection={<Icon icon="mdi:eye-outline" width={14} />}
                onClick={() => onPreview(version)}
                data-testid="version-preview"
              >
                Preview in a new tab
              </Menu.Item>
              <Menu.Item
                leftSection={
                  <Icon
                    icon={version.pinned ? 'mdi:bookmark-check' : 'mdi:bookmark-outline'}
                    width={14}
                  />
                }
                onClick={() => onBookmark(version)}
                data-testid="version-pin"
              >
                {version.pinned ? 'Edit bookmark' : 'Bookmark'}
              </Menu.Item>
              <Menu.Divider />
              {/* Unavailable stays focusable, with its reason written out: not
                  `disabled` or `data-disabled`, which the menu's arrow keys skip,
                  and a tooltip would not show on touch. */}
              <Menu.Item
                color={deleteBlocked ? undefined : 'red'}
                c={deleteBlocked ? 'dimmed' : undefined}
                leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                aria-disabled={deleteBlocked ? true : undefined}
                closeMenuOnClick={!deleteBlocked}
                style={deleteBlocked ? { cursor: 'not-allowed' } : undefined}
                onClick={() => {
                  if (!deleteBlocked) onDelete(version);
                }}
                data-testid="version-delete"
              >
                Delete
                {deleteBlocked && (
                  <Text component="span" size="xs" c="dimmed" display="block">
                    {deleteBlocked}
                  </Text>
                )}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>

          <ActionIcon
            variant="subtle"
            color="gray"
            size="md"
            aria-label={`Details of ${title}`}
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={toggle}
            data-testid="version-details-toggle"
          >
            <Icon icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={16} />
          </ActionIcon>
        </Group>
      </Group>

      <Collapse in={expanded} id={detailsId}>
        <Stack gap={2} pb={8} pl={DETAILS_INDENT}>
          {/* Full date and time, not just the clock: choosing between a day's
              autosaves needs the wall clock, choosing between months needs the
              date, and the day heading above scrolls out of view. */}
          <Group gap={6} wrap="wrap">
            <Badge
              size="xs"
              variant="light"
              color={meta.color}
              leftSection={<Icon icon={meta.icon} width={10} aria-hidden />}
              data-testid="version-kind"
            >
              {meta.label}
            </Badge>
            <Text size="xs" c="dimmed">
              {version.label ? `v${version.seq} · ` : ''}
              {absDateTime(version.created_at)}
            </Text>
          </Group>

          {version.author_email && (
            <Text size="xs" c="dimmed" truncate>
              {version.author_email}
            </Text>
          )}

          <Text size="xs" c="dimmed">
            {version.component_count} component{version.component_count === 1 ? '' : 's'}
            {version.tab_count > 1 ? ` · ${version.tab_count} tabs` : ''}
            {span ? ` · ${span}` : ''}
          </Text>

          {coverage && (
            <Text size="xs" c="dimmed">
              {coverage}
            </Text>
          )}
        </Stack>
      </Collapse>
    </Box>
  );
};

export default VersionTimelineItem;

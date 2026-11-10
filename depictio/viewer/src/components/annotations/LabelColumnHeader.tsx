import React from 'react';
import { ActionIcon, Group, Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** Where a label column lives, which decides its icon and its actions. */
export type LabelColumnKind =
  /** The reader's own, on their account (or in the browser for a temporary one). */
  | 'mine'
  /** The reader's own, from a dropped file: kept in this browser only. */
  | 'local'
  /** Shared on the dashboard, and this reader may change it. */
  | 'shared'
  /** Shared on the dashboard, read-only for this reader. */
  | 'shared-readonly';

/** What a label column's header can do; the panel supplies it per column. */
export interface LabelColumnActions {
  name: string;
  kind: LabelColumnKind;
  active: boolean;
  /** Why this column cannot drive the comparison, or null. */
  compareBlocked: string | null;
  /** Offered for a local column of an account that stores annotations. */
  canKeepOnAccount: boolean;
  /** Offered for the reader's own column when they may share on this dashboard. */
  canShare: boolean;
  /** Why this column cannot be written to the table, or null. */
  saveBlocked: string | null;
  onCompare: () => void;
  onRename: () => void;
  onKeepOnAccount: () => void;
  onShare: () => void;
  onStopSharing: () => void;
  onCopy: () => void;
  onSaveToTable: () => void;
  onDelete: () => void;
}

/** One icon and one sentence per kind, the same everywhere. */
export const LABEL_KIND: Record<LabelColumnKind, { icon: string; tip: string }> = {
  mine: { icon: 'mdi:tag-outline', tip: 'Your labels' },
  local: { icon: 'mdi:monitor', tip: 'Your labels from a file, kept in this browser only' },
  shared: {
    icon: 'mdi:account-group-outline',
    tip: 'Shared on this dashboard: everyone who opens it sees these labels',
  },
  'shared-readonly': {
    icon: 'mdi:account-group-outline',
    tip: 'Shared on this dashboard; read-only. Copy it to your labels to change it.',
  },
};

const Reason: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" c="dimmed" maw={260}>
    {children}
  </Text>
);

/**
 * AG Grid header of a label column: an icon saying where it lives, the name,
 * a dot on the compared column, and a menu holding every action on the
 * column. The grid is the whole UI; nothing about a column lives anywhere else.
 */
const LabelColumnHeader: React.FC<{ actions: LabelColumnActions }> = ({ actions: a }) => {
  const shared = a.kind === 'shared' || a.kind === 'shared-readonly';
  const writable = a.kind !== 'shared-readonly';
  return (
    <Group gap={6} wrap="nowrap" style={{ width: '100%', minWidth: 0 }} data-testid="label-header">
      <Tooltip withinPortal multiline w={260} label={LABEL_KIND[a.kind].tip}>
        <Icon
          icon={LABEL_KIND[a.kind].icon}
          width={14}
          data-testid={`label-kind-${a.kind}`}
          style={{ flexShrink: 0, color: 'var(--dc-panel-accent-ink, var(--mantine-color-dimmed))' }}
        />
      </Tooltip>
      <Text size="sm" fw={600} truncate style={{ minWidth: 0, flex: 1 }}>
        {a.name}
      </Text>
      <Tooltip
        withinPortal
        multiline
        w={240}
        label={
          a.active
            ? 'Comparing: the charts use these labels. Click to stop.'
            : a.compareBlocked
              ? a.compareBlocked
              : 'Compare in the charts: colour or split them by these labels. A temporary view, only you see it.'
        }
      >
        <button
          type="button"
          className="dc-label-compare"
          data-active={a.active || undefined}
          data-testid={a.active ? 'label-compared' : 'label-compare'}
          aria-pressed={a.active}
          aria-label={a.active ? 'Stop comparing by these labels' : 'Compare the charts by these labels'}
          disabled={!a.active && Boolean(a.compareBlocked)}
          onClick={a.onCompare}
        >
          <Icon icon="mdi:chart-scatter-plot" width={14} />
        </button>
      </Tooltip>
      <Menu withinPortal position="bottom-end" shadow="md">
        <Menu.Target>
          <ActionIcon
            size="xs"
            variant="subtle"
            color="gray"
            aria-label={`${a.name} column menu`}
            data-testid={`label-menu-${a.name}`}
          >
            <Icon icon="mdi:chevron-down" width={14} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            leftSection={<Icon icon="mdi:chart-scatter-plot" width={14} />}
            disabled={!a.active && Boolean(a.compareBlocked)}
            onClick={a.onCompare}
          >
            {a.active ? 'Stop comparing' : 'Compare in the charts'}
            {!a.active && a.compareBlocked ? (
              <Reason>{a.compareBlocked}</Reason>
            ) : (
              !a.active && <Reason>A temporary view: only you see it, and the dashboard is not changed.</Reason>
            )}
          </Menu.Item>
          {writable && (
            <Menu.Item leftSection={<Icon icon="mdi:pencil-outline" width={14} />} onClick={a.onRename}>
              Rename
            </Menu.Item>
          )}
          {shared && (
            <Menu.Item
              leftSection={<Icon icon="mdi:content-copy" width={14} />}
              onClick={a.onCopy}
              data-testid="label-copy"
            >
              Copy to my labels
              <Reason>A copy of your own, which you can change.</Reason>
            </Menu.Item>
          )}
          {a.canKeepOnAccount && (
            <Menu.Item
              leftSection={<Icon icon="mdi:cloud-upload-outline" width={14} />}
              onClick={a.onKeepOnAccount}
            >
              Keep on my account
              <Reason>Its labels are sent to the server.</Reason>
            </Menu.Item>
          )}
          {!shared && a.canShare && (
            <Menu.Item
              leftSection={<Icon icon={LABEL_KIND.shared.icon} width={14} />}
              onClick={a.onShare}
              data-testid="label-share"
            >
              Share on this dashboard
              <Reason>Everyone who opens this dashboard sees it, read-only.</Reason>
            </Menu.Item>
          )}
          {a.kind === 'shared' && (
            <Menu.Item
              leftSection={<Icon icon="mdi:account-arrow-left-outline" width={14} />}
              onClick={a.onStopSharing}
              data-testid="label-stop-sharing"
            >
              Stop sharing
              <Reason>It becomes one of your own labels again.</Reason>
            </Menu.Item>
          )}
          {writable && (
            <Menu.Item
              leftSection={<Icon icon="mdi:table-column-plus-after" width={14} />}
              disabled={Boolean(a.saveBlocked)}
              onClick={a.onSaveToTable}
            >
              Save to table
              {a.saveBlocked && <Reason>{a.saveBlocked}</Reason>}
            </Menu.Item>
          )}
          {writable && (
            <>
              <Menu.Divider />
              <Menu.Item
                color="red"
                leftSection={<Icon icon="mdi:trash-can-outline" width={14} />}
                onClick={a.onDelete}
              >
                Delete
                {a.kind === 'shared' && <Reason>Removes it for everyone.</Reason>}
              </Menu.Item>
            </>
          )}
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
};

export default LabelColumnHeader;

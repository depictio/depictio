/**
 * One row of the folder browser's tree, as Mantine's `Tree` asks for it in
 * `renderNode`: a source group ("This computer", "S3"), a folder, or a
 * placeholder standing in for a folder's children (loading, empty, cut
 * short, or failed with a retry).
 */
import React from 'react';
import { Anchor, Box, Group, Loader, Text } from '@mantine/core';
import type { RenderTreeNodePayload } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FolderSource } from 'depictio-react-core';

import { FlowBadge } from '../FlowBadge';
import type { PlaceholderKind, TreeNodeProps } from './useFolderTree';

export const SOURCE_ICON: Record<FolderSource, string> = {
  local: 'mdi:laptop',
  s3: 'mdi:cloud-outline',
};

function folderIcon(isRun: boolean, expanded: boolean): string {
  if (isRun) return 'mdi:folder-check-outline';
  return expanded ? 'mdi:folder-open-outline' : 'mdi:folder-outline';
}

const PlaceholderContent: React.FC<{
  kind: PlaceholderKind | undefined;
  /** The error message, for an `error` placeholder. */
  label: string;
  /** Lists the folder again; null when the placeholder stands for none. */
  onRetry: (() => void) | null;
}> = ({ kind, label, onRetry }) => {
  switch (kind) {
    case 'loading':
      return (
        <>
          <Loader size={12} />
          <Text size="xs" c="dimmed">
            Listing folders...
          </Text>
        </>
      );
    case 'empty':
      return (
        <Text size="xs" c="dimmed" data-testid="browse-tree-empty">
          No folder is available here.
        </Text>
      );
    case 'truncated':
      return (
        <Text size="xs" c="dimmed" data-testid="browse-tree-truncated">
          Only the first 500 folders are listed. Type a path above to reach the others.
        </Text>
      );
    case 'error':
      return (
        <Group gap={6} wrap="nowrap" data-testid="browse-tree-error">
          <Text size="xs" c="red">
            {label || 'This folder could not be listed.'}
          </Text>
          {onRetry && (
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={(event) => {
                event.stopPropagation();
                onRetry();
              }}
            >
              Try again
            </Anchor>
          )}
        </Group>
      );
    default:
      return null;
  }
};

interface FolderTreeNodeProps {
  payload: RenderTreeNodePayload;
  /** Whether a folder looks like a run folder, as far as is known. */
  isRun: (path: string) => boolean;
  onSelect: (path: string) => void;
  /** Forget a failed listing of `parent` and try it again. */
  onRetry: (parent: string) => void;
}

export const FolderTreeNode: React.FC<FolderTreeNodeProps> = ({
  payload,
  isRun,
  onSelect,
  onRetry,
}) => {
  const { node, expanded, hasChildren, elementProps, tree: controller } = payload;
  const props = (node.nodeProps ?? {}) as TreeNodeProps;

  if (props.kind === 'placeholder') {
    const { parent } = props;
    return (
      <Group gap={6} wrap="nowrap" py={4} {...elementProps} style={{ ...elementProps.style, cursor: 'default' }}>
        <Box w={18} style={{ flexShrink: 0 }} />
        <PlaceholderContent
          kind={props.placeholder}
          label={String(node.label)}
          onRetry={parent ? () => onRetry(parent) : null}
        />
      </Group>
    );
  }

  const chevron = (
    <Box
      w={18}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
      onClick={(event) => {
        if (!hasChildren) return;
        event.stopPropagation();
        controller.toggleExpanded(node.value);
      }}
      aria-hidden
      data-testid={hasChildren ? 'browse-tree-chevron' : undefined}
    >
      {hasChildren && (
        <Icon icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
      )}
    </Box>
  );

  if (props.kind === 'group') {
    const source = props.source ?? 'local';
    return (
      <Group
        gap={6}
        wrap="nowrap"
        py={6}
        {...elementProps}
        onClick={(event) => {
          elementProps.onClick(event);
          controller.toggleExpanded(node.value);
        }}
        data-testid={`browse-group-${source}`}
      >
        {chevron}
        <Icon icon={SOURCE_ICON[source]} width={16} />
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          {node.label}
        </Text>
      </Group>
    );
  }

  const run = isRun(node.value);
  return (
    <Group
      gap={6}
      wrap="nowrap"
      py={4}
      pr="xs"
      {...elementProps}
      style={{ ...elementProps.style, borderRadius: 'var(--mantine-radius-sm)' }}
      onClick={(event) => {
        elementProps.onClick(event);
        onSelect(node.value);
      }}
      onDoubleClick={() => hasChildren && controller.toggleExpanded(node.value)}
      data-testid="browse-tree-node"
      data-path={node.value}
      data-run-folder={run || undefined}
    >
      {chevron}
      <Icon icon={folderIcon(run, expanded)} width={16} style={{ flexShrink: 0 }} />
      <Text size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
        {node.label}
      </Text>
      {run && <FlowBadge status="run-folder" />}
    </Group>
  );
};

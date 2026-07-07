/**
 * Left column: the run-directory tree with checkboxes to pick 1..n files and a
 * single "active" file (the one previewed in the middle column).
 */
import React, { useState } from 'react';
import { Box, Checkbox, Group, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { TreeNode } from './backend';

interface Props {
  tree: TreeNode | null;
  activeFile: string | null;
  picked: Set<string>;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
}

const Node: React.FC<{
  node: TreeNode;
  depth: number;
  activeFile: string | null;
  picked: Set<string>;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
}> = ({ node, depth, activeFile, picked, onActivate, onTogglePick }) => {
  const [open, setOpen] = useState(depth < 1);

  if (node.type === 'dir') {
    return (
      <Box>
        <UnstyledButton
          onClick={() => setOpen((v) => !v)}
          style={{ display: 'block', width: '100%', padding: '2px 0', paddingLeft: depth * 14 }}
        >
          <Group gap={4} wrap="nowrap">
            <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
            <Icon icon="mdi:folder-outline" width={14} color="var(--mantine-color-yellow-6)" />
            <Text size="sm" lineClamp={1}>
              {node.name}
            </Text>
          </Group>
        </UnstyledButton>
        {open &&
          (node.children || []).map((c) => (
            <Node
              key={c.path}
              node={c}
              depth={depth + 1}
              activeFile={activeFile}
              picked={picked}
              onActivate={onActivate}
              onTogglePick={onTogglePick}
            />
          ))}
      </Box>
    );
  }

  const active = node.path === activeFile;
  return (
    <Group
      gap={6}
      wrap="nowrap"
      style={{
        paddingLeft: depth * 14 + 4,
        paddingTop: 2,
        paddingBottom: 2,
        borderRadius: 4,
        background: active ? 'var(--mantine-color-default-hover)' : undefined,
      }}
    >
      <Checkbox
        size="xs"
        checked={picked.has(node.path)}
        disabled={!node.previewable}
        onChange={() => onTogglePick(node.path)}
      />
      <UnstyledButton
        onClick={() => node.previewable && onActivate(node.path)}
        style={{ flex: 1, minWidth: 0 }}
      >
        <Group gap={4} wrap="nowrap">
          <Icon
            icon={node.previewable ? 'mdi:table' : 'mdi:file-outline'}
            width={14}
            color={node.previewable ? 'var(--mantine-color-blue-5)' : 'var(--mantine-color-dimmed)'}
          />
          <Text size="sm" c={node.previewable ? undefined : 'dimmed'} lineClamp={1}>
            {node.name}
          </Text>
        </Group>
      </UnstyledButton>
    </Group>
  );
};

const FileTree: React.FC<Props> = ({ tree, activeFile, picked, onActivate, onTogglePick }) => {
  if (!tree) return <Text size="sm" c="dimmed" p="sm">Loading tree…</Text>;
  return (
    <Box p="xs">
      {(tree.children || []).map((c) => (
        <Node
          key={c.path}
          node={c}
          depth={0}
          activeFile={activeFile}
          picked={picked}
          onActivate={onActivate}
          onTogglePick={onTogglePick}
        />
      ))}
    </Box>
  );
};

export default FileTree;

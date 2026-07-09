/**
 * Left column: the run-directory tree with checkboxes to pick 1..n files and a
 * single "active" file (the one previewed in the middle column).
 *
 * Rows never truncate — long paths overflow horizontally and the surrounding
 * ScrollArea scrolls. Two kinds of highlight: files the *current* scan glob
 * resolves to (`matched`, live while configuring a DC) get a teal-tinted row;
 * files already claimed by a *created* DC (`assigned`) also carry its tag badge.
 */
import React, { useState } from 'react';
import { Badge, Box, Checkbox, Group, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { TreeNode } from './backend';

interface Props {
  tree: TreeNode | null;
  activeFile: string | null;
  picked: Set<string>;
  /** Files the current (in-progress) scan matches — live highlight. */
  matched: Set<string>;
  /** path → data-collection tag, for files already claimed by a created DC. */
  assigned: Map<string, string>;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
}

// Rows stretch to the full scroll width so highlights span it, but never wrap.
const ROW_WIDTH: React.CSSProperties = { minWidth: '100%', width: 'max-content' };
const NOWRAP: React.CSSProperties = { whiteSpace: 'nowrap' };

const Node: React.FC<{
  node: TreeNode;
  depth: number;
  activeFile: string | null;
  picked: Set<string>;
  matched: Set<string>;
  assigned: Map<string, string>;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
}> = ({ node, depth, activeFile, picked, matched, assigned, onActivate, onTogglePick }) => {
  const [open, setOpen] = useState(depth < 1);

  if (node.type === 'dir') {
    return (
      <Box>
        <UnstyledButton
          onClick={() => setOpen((v) => !v)}
          style={{ display: 'block', padding: '2px 0', paddingLeft: depth * 14, ...ROW_WIDTH }}
        >
          <Group gap={4} wrap="nowrap">
            <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
            <Icon icon="mdi:folder-outline" width={14} color="var(--mantine-color-yellow-6)" />
            <Text size="sm" style={NOWRAP}>
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
              matched={matched}
              assigned={assigned}
              onActivate={onActivate}
              onTogglePick={onTogglePick}
            />
          ))}
      </Box>
    );
  }

  const active = node.path === activeFile;
  const isMatch = matched.has(node.path);
  const dcTag = assigned.get(node.path);
  return (
    <Group
      gap={6}
      wrap="nowrap"
      style={{
        ...ROW_WIDTH,
        paddingLeft: depth * 14 + 4,
        paddingTop: 2,
        paddingBottom: 2,
        borderRadius: 4,
        // A teal left-accent + tint marks every file the current scan matches —
        // including the active one (its checkbox marks it as the primary example),
        // so all matched files read uniformly. The border is always reserved
        // (transparent) so text never shifts.
        borderLeft: `2px solid ${isMatch ? 'var(--mantine-color-teal-5)' : 'transparent'}`,
        background: isMatch
          ? 'var(--mantine-color-teal-light)'
          : active
            ? 'var(--mantine-color-default-hover)'
            : undefined,
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
        style={NOWRAP}
      >
        <Group gap={4} wrap="nowrap">
          <Icon
            icon={dcTag ? 'mdi:database-check' : node.previewable ? 'mdi:table' : 'mdi:file-outline'}
            width={14}
            color={
              dcTag
                ? 'var(--mantine-color-teal-6)'
                : node.previewable
                  ? 'var(--mantine-color-blue-5)'
                  : 'var(--mantine-color-dimmed)'
            }
          />
          <Text size="sm" c={node.previewable ? undefined : 'dimmed'} style={NOWRAP}>
            {node.name}
          </Text>
        </Group>
      </UnstyledButton>
      {dcTag && (
        <Tooltip label={`In data collection “${dcTag}”`} withArrow>
          <Badge
            size="xs"
            variant="light"
            color="teal"
            radius="sm"
            tt="none"
            style={{ flexShrink: 0 }}
          >
            {dcTag}
          </Badge>
        </Tooltip>
      )}
    </Group>
  );
};

const FileTree: React.FC<Props> = ({
  tree,
  activeFile,
  picked,
  matched,
  assigned,
  onActivate,
  onTogglePick,
}) => {
  if (!tree)
    return (
      <Text size="sm" c="dimmed" p="sm">
        Loading tree…
      </Text>
    );
  return (
    <Box p="xs" style={{ width: '100%', minWidth: 'max-content' }}>
      {(tree.children || []).map((c) => (
        <Node
          key={c.path}
          node={c}
          depth={0}
          activeFile={activeFile}
          picked={picked}
          matched={matched}
          assigned={assigned}
          onActivate={onActivate}
          onTogglePick={onTogglePick}
        />
      ))}
    </Box>
  );
};

export default FileTree;

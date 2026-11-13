/**
 * One saved collection as a compact card: tag, type, mode and how many files
 * it claimed, its file or pattern (full scan settings on hover), and
 * edit / move / remove actions.
 */
import React from 'react';
import { ActionIcon, Badge, Code, Group, Menu, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderDcDraft, BuilderWorkflowState } from 'depictio-react-core';

import { BuilderDcTypeIcon, DC_TYPE_META } from './dcTypes';

export const DcCard: React.FC<{
  dc: BuilderDcDraft;
  /** Files the collection matched when saved. */
  files?: string[];
  active?: boolean;
  onEdit?: () => void;
  onRemove?: () => void;
  /** Other workflows it can move to. */
  moveTargets?: BuilderWorkflowState[];
  onMove?: (workflowId: string) => void;
}> = ({ dc, files, active = false, onEdit, onRemove, moveTargets = [], onMove }) => {
  const accent = useBrandAccents();
  const target = dc.mode === 'recursive' ? dc.glob || dc.regex : dc.path;
  const summary = (
    <Stack gap={1}>
      <Text size="xs">type: {DC_TYPE_META[dc.type].label}</Text>
      <Text size="xs">mode: {dc.mode}</Text>
      {dc.mode === 'single' ? (
        <Text size="xs">file: {dc.path}</Text>
      ) : (
        <>
          {dc.glob && <Text size="xs">glob: {dc.glob}</Text>}
          <Text size="xs">regex: {dc.regex}</Text>
        </>
      )}
      {dc.max_depth != null && <Text size="xs">max depth: {dc.max_depth}</Text>}
      {dc.ignore?.length ? <Text size="xs">ignore: {dc.ignore.join(', ')}</Text> : null}
      {dc.optional && <Text size="xs">optional</Text>}
    </Stack>
  );
  return (
    <Paper
      withBorder
      radius="sm"
      px="sm"
      py={6}
      style={{
        borderColor: active ? `var(--mantine-color-${accent.secondary}-5)` : undefined,
      }}
      data-testid="builder-dc-card"
      data-tag={dc.tag}
    >
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" gap={4}>
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <BuilderDcTypeIcon type={dc.type} size={16} />
            <Tooltip label={dc.tag} withArrow openDelay={300}>
              <Text size="sm" fw={600} truncate>
                {dc.tag}
              </Text>
            </Tooltip>
          </Group>
          <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
            {onEdit && (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={onEdit}
                aria-label={`Edit ${dc.tag}`}
                data-testid="builder-dc-card-edit"
              >
                <Icon icon="mdi:pencil-outline" width={15} />
              </ActionIcon>
            )}
            {onMove && moveTargets.length > 0 && (
              <Menu withinPortal position="bottom-end" shadow="md">
                <Menu.Target>
                  <ActionIcon variant="subtle" color="gray" size="sm" aria-label={`Move ${dc.tag}`}>
                    <Icon icon="mdi:folder-move-outline" width={15} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>Move to workflow</Menu.Label>
                  {moveTargets.map((w) => (
                    <Menu.Item key={w.id} onClick={() => onMove(w.id)}>
                      {w.name || '(unnamed)'}
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>
            )}
            {onRemove && (
              <ActionIcon
                variant="subtle"
                color="red"
                size="sm"
                onClick={onRemove}
                aria-label={`Remove ${dc.tag}`}
                data-testid="builder-dc-card-remove"
              >
                <Icon icon="mdi:close" width={15} />
              </ActionIcon>
            )}
          </Group>
        </Group>
        <Group gap={4}>
          <Badge size="xs" variant="light" color={dc.mode === 'recursive' ? 'grape' : 'blue'} tt="none">
            {dc.mode === 'recursive' ? 'scan' : 'one file'}
          </Badge>
          {files && dc.mode === 'recursive' && (
            <Badge size="xs" variant="default" radius="sm" tt="none">
              {files.length} file{files.length === 1 ? '' : 's'}
            </Badge>
          )}
          {dc.optional && (
            <Badge size="xs" variant="light" color="gray" tt="none">
              optional
            </Badge>
          )}
        </Group>
        <Tooltip label={summary} withArrow multiline position="left" openDelay={200}>
          <Code fz="xs" block style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {target || '(no file)'}
          </Code>
        </Tooltip>
      </Stack>
    </Paper>
  );
};

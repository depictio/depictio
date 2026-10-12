/**
 * The workflows of the project, each selectable and removable (one always
 * stays), listing its collections as cards that open for editing and move
 * between workflows.
 */
import React from 'react';
import { ActionIcon, Badge, Group, Paper, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { isWorkflowNameTaken, useBrandAccents } from 'depictio-react-core';
import type { BuilderState } from 'depictio-react-core';

import { DcCard } from '../collections/DcCard';
import { engineLabel, WorkflowLogo } from './WorkflowLogo';

export const WorkflowTree: React.FC<{
  state: BuilderState;
  /** The collection open in the editor, highlighted. */
  editingTag: string | null;
  onSelect: (workflowId: string) => void;
  onRemove: (workflowId: string) => void;
  onEditDc: (tag: string) => void;
  onRemoveDc: (tag: string) => void;
  onMoveDc: (tag: string, workflowId: string) => void;
}> = ({ state, editingTag, onSelect, onRemove, onEditDc, onRemoveDc, onMoveDc }) => {
  const accent = useBrandAccents();
  const single = state.workflows.length <= 1;
  return (
    <Stack gap={10} data-testid="builder-workflow-tree">
      {state.workflows.map((w) => {
        const active = w.id === state.activeWorkflowId;
        const clash = isWorkflowNameTaken(state, w.name, w.id) || !w.name.trim();
        return (
          <Paper
            key={w.id}
            withBorder
            radius="sm"
            p={6}
            style={{
              borderColor: active ? `var(--mantine-color-${accent.secondary}-5)` : undefined,
              background: active ? `var(--mantine-color-${accent.secondary}-light)` : undefined,
            }}
            data-testid="builder-workflow-item"
            data-workflow={w.name}
            data-active={active || undefined}
          >
            <Group justify="space-between" wrap="nowrap" gap={4}>
              <UnstyledButton
                onClick={() => onSelect(w.id)}
                style={{ flex: 1, minWidth: 0 }}
                aria-pressed={active}
              >
                <Group gap={6} wrap="nowrap">
                  <WorkflowLogo engine={w.engine} catalog={w.catalog?.name} size={16} />
                  <Text size="sm" fw={600} truncate c={clash ? 'red' : undefined}>
                    {w.name || '(unnamed)'}
                  </Text>
                  <Badge size="xs" variant="light" color="gray" tt="none" style={{ flexShrink: 0 }}>
                    {engineLabel(w.engine)}
                  </Badge>
                  <Badge size="xs" variant="light" color={accent.secondary} style={{ flexShrink: 0 }}>
                    {w.data_collections.length}
                  </Badge>
                </Group>
              </UnstyledButton>
              <Tooltip label={single ? 'A project keeps at least one workflow' : 'Remove workflow'} withArrow>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  data-disabled={single || undefined}
                  aria-disabled={single || undefined}
                  onClick={() => !single && onRemove(w.id)}
                  aria-label={`Remove workflow ${w.name}`}
                  style={{ flexShrink: 0 }}
                >
                  <Icon icon="mdi:close" width={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
            {w.data_collections.length > 0 ? (
              <Stack gap={4} pt={6}>
                {w.data_collections.map((dc) => (
                  <DcCard
                    key={dc.tag}
                    dc={dc}
                    files={state.claimed[dc.tag]}
                    active={dc.tag === editingTag}
                    onEdit={() => onEditDc(dc.tag)}
                    onRemove={() => onRemoveDc(dc.tag)}
                    moveTargets={state.workflows.filter((o) => o.id !== w.id)}
                    onMove={(to) => onMoveDc(dc.tag, to)}
                  />
                ))}
              </Stack>
            ) : (
              <Text size="xs" c="dimmed" pl={22} pt={2}>
                No data collection yet.
              </Text>
            )}
          </Paper>
        );
      })}
    </Stack>
  );
};

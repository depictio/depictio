/**
 * The workflows of the project, each selectable and removable (one always
 * stays), listing its collections as cards that open for editing and move
 * between workflows. A workflow of the template the draft edits also lists
 * the template's collections, folded, each opening in the template panel.
 */
import React, { useState } from 'react';
import { ActionIcon, Collapse, Group, Paper, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { baseRemoved, isWorkflowNameTaken, useBrandAccents } from 'depictio-react-core';
import type { BuilderState, BuilderWorkflowState } from 'depictio-react-core';

import { FactBadge } from '../../badges';
import { DcTypeIcon } from '../../dcTypeIcon';
import { DcCard } from '../collections/DcCard';
import { shownWorkflowName } from './shownName';
import { EngineBadge, WorkflowLogo } from './WorkflowLogo';

export const WorkflowTree: React.FC<{
  state: BuilderState;
  /** The collection open in the editor, highlighted. */
  editingTag: string | null;
  onSelect: (workflowId: string) => void;
  onRemove: (workflowId: string) => void;
  onEditDc: (tag: string) => void;
  onRemoveDc: (tag: string) => void;
  onMoveDc: (tag: string, workflowId: string) => void;
  /** Open a template collection in the template panel. */
  onFocusBase?: (workflowId: string, tag: string) => void;
}> = ({ state, editingTag, onSelect, onRemove, onEditDc, onRemoveDc, onMoveDc, onFocusBase }) => {
  const accent = useBrandAccents();
  const single = state.workflows.length <= 1;
  const removed = baseRemoved(state.base);
  const shippedOf = (w: BuilderWorkflowState) =>
    w.fromTemplate ? state.base?.template.workflows.find((t) => t.name === w.name)?.collections ?? [] : [];
  return (
    <Stack gap={10} data-testid="builder-workflow-tree">
      {state.workflows.map((w) => {
        const active = w.id === state.activeWorkflowId;
        const clash = isWorkflowNameTaken(state, w.name, w.id) || !w.name.trim();
        const shipped = shippedOf(w);
        const kept = shipped.filter((c) => !removed.has(c.tag)).length;
        const locked = single || Boolean(w.fromTemplate);
        const removeLabel = w.fromTemplate
          ? "The template's workflow stays: remove its collections instead"
          : single
            ? 'A project keeps at least one workflow'
            : 'Remove workflow';
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
                    {shownWorkflowName(state, w) || '(unnamed)'}
                  </Text>
                  <EngineBadge engine={w.engine} />
                  <Tooltip label="Collections in this workflow" withArrow>
                    <FactBadge icon="mdi:database-outline">{w.data_collections.length + kept}</FactBadge>
                  </Tooltip>
                </Group>
              </UnstyledButton>
              <Tooltip label={removeLabel} withArrow>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  data-disabled={locked || undefined}
                  aria-disabled={locked || undefined}
                  onClick={() => !locked && onRemove(w.id)}
                  aria-label={`Remove workflow ${w.name}`}
                  style={{ flexShrink: 0 }}
                >
                  <Icon icon="mdi:close" width={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
            {shipped.length > 0 && (
              <ShippedList
                collections={shipped}
                removed={removed}
                onOpen={(tag) => onFocusBase?.(w.id, tag)}
              />
            )}
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
              shipped.length === 0 && (
                <Text size="xs" c="dimmed" pl={22} pt={2}>
                  No data collection yet.
                </Text>
              )
            )}
          </Paper>
        );
      })}
    </Stack>
  );
};

/** The template's collections of one workflow, folded under a count. */
const ShippedList: React.FC<{
  collections: { tag: string; type: string }[];
  removed: Map<string, string>;
  onOpen: (tag: string) => void;
}> = ({ collections, removed, onOpen }) => {
  const [open, setOpen] = useState(false);
  const gone = collections.filter((c) => removed.has(c.tag)).length;
  return (
    <Stack gap={2} pt={6} data-testid="builder-tree-template">
      <UnstyledButton onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="builder-tree-template-toggle">
        <Group gap={4} wrap="nowrap" pl={2}>
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
          <Text size="xs" c="dimmed">
            {collections.length - gone} from the template{gone ? ` (${gone} removed)` : ''}
          </Text>
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Stack gap={0} pl={18}>
          {collections.map((c) => {
            const out = removed.has(c.tag);
            return (
              <UnstyledButton
                key={c.tag}
                onClick={() => onOpen(c.tag)}
                style={{ opacity: out ? 0.5 : undefined, borderRadius: 4 }}
                px={4}
                py={1}
                data-testid="builder-tree-template-item"
                data-tag={c.tag}
              >
                <Group gap={6} wrap="nowrap">
                  <DcTypeIcon type={c.type} size={13} withTooltip={false} />
                  <Text size="xs" ff="monospace" truncate td={out ? 'line-through' : undefined}>
                    {c.tag}
                  </Text>
                </Group>
              </UnstyledButton>
            );
          })}
        </Stack>
      </Collapse>
    </Stack>
  );
};

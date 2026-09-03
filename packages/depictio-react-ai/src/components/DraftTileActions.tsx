import React, { useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Loader,
  Popover,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON } from '../icons';

export interface DraftTileActionsProps {
  /** Generation handle of this tile — what the review route addresses it
   *  by, and what the strip reports back so a host can key its own state. */
  tag: string;
  /** Already been through: the strip shows a subdued check instead of the
   *  Keep affordance, and `data-reviewed` says so. */
  reviewed: boolean;
  /** This tile's regeneration is streaming. */
  busy?: boolean;
  /** Another tile is regenerating, or the host is otherwise mid-write: the
   *  actions go inert so two runs cannot overlap on one draft. */
  disabled?: boolean;
  /** Grid section this tile sits in. When set (and `onRegenerateSection` is
   *  wired), the popover also offers to refill the whole section. */
  section?: string | null;
  onRegenerate: (instruction: string) => void | Promise<void>;
  onRegenerateSection?: (instruction: string) => void | Promise<void>;
  onKeep: () => void | Promise<void>;
  onRemove: () => void | Promise<void>;
  /** Last failure for this tile, shown inside the popover so the message
   *  lands where the action that raised it was taken. */
  error?: string | null;
}

/**
 * The per-tile review strip of an AI-generated draft.
 *
 * Rendered into the component chrome's action row (see `draftActions` /
 * `DraftReviewContext` in depictio-react-core), so reviewing a draft is done
 * where the tile is rather than in a list that names components the reader
 * then has to find. Three decisions, in the order they get taken: regenerate
 * this one (optionally saying what to change), keep it as it is, or drop it
 * from the draft.
 *
 * The strip owns no state beyond the popover and its draft instruction: what
 * has been reviewed lives on the dashboard document, and the host is what
 * knows whether a run is in flight.
 */
const DraftTileActions: React.FC<DraftTileActionsProps> = ({
  tag,
  reviewed,
  busy = false,
  disabled = false,
  section,
  onRegenerate,
  onRegenerateSection,
  onKeep,
  onRemove,
  error,
}) => {
  const [opened, setOpened] = useState(false);
  const [instruction, setInstruction] = useState('');
  const inert = busy || disabled;

  const regenerate = () => {
    setOpened(false);
    void onRegenerate(instruction.trim());
  };

  const regenerateSection = () => {
    if (!onRegenerateSection) return;
    setOpened(false);
    void onRegenerateSection(instruction.trim());
  };

  return (
    <Group
      gap={2}
      wrap="nowrap"
      data-testid="draft-tile-actions"
      data-tag={tag}
      data-reviewed={reviewed ? 'true' : 'false'}
    >
      {busy ? (
        <Loader size="xs" color={AI_COLOR} data-testid="draft-tile-busy" />
      ) : (
        <Popover
          opened={opened}
          onChange={setOpened}
          position="bottom-end"
          width={280}
          shadow="md"
          trapFocus
        >
          <Popover.Target>
            <Tooltip label="Regenerate this component" openDelay={300}>
              <ActionIcon
                variant="subtle"
                color={AI_COLOR}
                size="sm"
                aria-label="Regenerate this component"
                disabled={inert}
                onClick={() => setOpened((o) => !o)}
                data-testid="draft-tile-regenerate"
              >
                <Icon icon="mdi:refresh" width={16} height={16} />
              </ActionIcon>
            </Tooltip>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              <Group gap={6}>
                <Icon icon={AI_ICON} width={14} />
                <Text size="sm" fw={600}>
                  Regenerate
                </Text>
              </Group>
              <Textarea
                label="Anything to change?"
                description="Optional. Left empty, the component is filled again from the plan's own intent."
                placeholder="e.g. use a box plot, group by cohort"
                autosize
                minRows={2}
                maxRows={5}
                value={instruction}
                onChange={(e) => setInstruction(e.currentTarget.value)}
                data-testid="draft-tile-instruction"
              />
              {error && (
                <Text size="xs" c="red">
                  {error}
                </Text>
              )}
              <Group justify="flex-end" gap="xs">
                {section && onRegenerateSection && (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color={AI_COLOR}
                    onClick={regenerateSection}
                    data-testid="draft-tile-regenerate-section"
                  >
                    Whole section
                  </Button>
                )}
                <Button
                  size="compact-sm"
                  color={AI_COLOR}
                  leftSection={<Icon icon="mdi:refresh" width={14} />}
                  onClick={regenerate}
                  data-testid="draft-tile-regenerate-run"
                >
                  Regenerate
                </Button>
              </Group>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      )}

      {/* Keep stays clickable once reviewed — it is a toggle back to
          unreviewed — but drops to a subdued grey check, so a tile that has
          been through review reads differently from one that has not. */}
      <Tooltip label={reviewed ? 'Reviewed' : 'Keep this component'} openDelay={300}>
        <ActionIcon
          variant="subtle"
          color={reviewed ? 'gray' : 'teal'}
          size="sm"
          aria-label={reviewed ? 'Reviewed' : 'Keep this component'}
          disabled={inert}
          onClick={() => void onKeep()}
          data-testid="draft-tile-keep"
        >
          <Icon
            icon={reviewed ? 'mdi:check-circle' : 'mdi:check'}
            width={16}
            height={16}
          />
        </ActionIcon>
      </Tooltip>

      <Tooltip label="Remove from the draft" openDelay={300}>
        <ActionIcon
          variant="subtle"
          color="red"
          size="sm"
          aria-label="Remove from the draft"
          disabled={inert}
          onClick={() => void onRemove()}
          data-testid="draft-tile-remove"
        >
          <Icon icon="mdi:delete-outline" width={16} height={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
};

export default DraftTileActions;

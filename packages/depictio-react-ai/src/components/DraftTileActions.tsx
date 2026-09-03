import React, { useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Popover,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';

export interface DraftTileActionsProps {
  /** Generation handle of this tile — what the review route addresses it
   *  by, and what the control reports back so a host can key its own state. */
  tag: string;
  /** Already been through: the trigger drops to a subdued check, and
   *  `data-reviewed` says so. */
  reviewed: boolean;
  /** This tile's regeneration is streaming. */
  busy?: boolean;
  /** Another tile is regenerating, or the host is otherwise mid-write: the
   *  actions go inert so two runs cannot overlap on one draft. */
  disabled?: boolean;
  /** Grid section this tile sits in. When set (and `onRegenerateSection` is
   *  wired), the popover also offers to refill the whole section. */
  section?: string | null;
  /** The planner's brief for this tile ("what should this show"), so the
   *  reviewer can see why it exists before deciding. Empty on a tile whose
   *  stamp predates the rationale. */
  intent?: string | null;
  /** The planner's reason for the section this tile sits in. */
  sectionRationale?: string | null;
  onRegenerate: (instruction: string) => void | Promise<void>;
  onRegenerateSection?: (instruction: string) => void | Promise<void>;
  onKeep: () => void | Promise<void>;
  onRemove: () => void | Promise<void>;
  /** Last failure for this tile, shown inside the popover so the message
   *  lands where the action that raised it was taken. */
  error?: string | null;
}

/**
 * The per-tile review control of an AI-generated draft.
 *
 * Rendered into the component chrome's action row (see `draftActions` /
 * `DraftReviewContext` in depictio-react-core), so reviewing a draft is done
 * where the tile is rather than in a list that names components the reader
 * then has to find. That row is permanently visible on a draft, so the tile
 * carries exactly one mark — the AI sparkle, greyed to a check once the tile
 * has been through — and every decision lives inside the popover it opens:
 * why the planner asked for this tile, regenerate it (or its whole section),
 * keep it, drop it. Three always-on icons per tile read as clutter on a
 * dashboard of twelve.
 *
 * The control owns no state beyond the popover and its draft instruction:
 * what has been reviewed lives on the dashboard document, and the host is
 * what knows whether a run is in flight.
 */
const DraftTileActions: React.FC<DraftTileActionsProps> = ({
  tag,
  reviewed,
  busy = false,
  disabled = false,
  section,
  intent,
  sectionRationale,
  onRegenerate,
  onRegenerateSection,
  onKeep,
  onRemove,
  error,
}) => {
  const [opened, setOpened] = useState(false);
  const [instruction, setInstruction] = useState('');
  const inert = busy || disabled;
  const brief = (intent ?? '').trim();
  const why = (sectionRationale ?? '').trim();

  const regenerate = () => {
    setOpened(false);
    void onRegenerate(instruction.trim());
  };

  const regenerateSection = () => {
    if (!onRegenerateSection) return;
    setOpened(false);
    void onRegenerateSection(instruction.trim());
  };

  /** Both verdicts end the review of this tile, so they take the popover with
   *  them rather than leaving it open over a tile nobody is deciding on. */
  const keep = () => {
    setOpened(false);
    void onKeep();
  };

  const remove = () => {
    setOpened(false);
    void onRemove();
  };

  const label = reviewed ? 'Reviewed - open the AI review' : 'Review this AI component';

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
          width={320}
          shadow="md"
          trapFocus
        >
          <Popover.Target>
            <Tooltip label={label} openDelay={300}>
              {/* Reviewed reads as a settled tile: grey and subdued, but still
                  the way back in, since Keep is a toggle. */}
              <ActionIcon
                variant={reviewed ? 'subtle' : 'light'}
                color={reviewed ? 'gray' : AI_COLOR}
                size="sm"
                aria-label={label}
                disabled={inert}
                onClick={() => setOpened((o) => !o)}
                data-testid="draft-tile-regenerate"
              >
                <Icon
                  icon={reviewed ? 'mdi:check-circle' : AI_ICON}
                  width={16}
                  height={16}
                />
              </ActionIcon>
            </Tooltip>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              <Group gap={6} wrap="nowrap" justify="space-between">
                <Group gap={6} wrap="nowrap">
                  <Icon icon={AI_ICON} width={14} />
                  <Text size="sm" fw={600}>
                    AI review
                  </Text>
                </Group>
                <Text size="xs" c="dimmed" truncate style={{ minWidth: 0 }}>
                  {tag}
                </Text>
              </Group>

              {/* The planner's own words, quoted rather than alerted: this is
                  context for the decision, not something that went wrong. */}
              {(brief || why) && (
                <Box
                  pl="xs"
                  style={{ borderLeft: `2px solid ${aiColorVar(3)}` }}
                >
                  <Text fw={500} size="xs">
                    {brief ? 'Why this component' : 'Why this section'}
                  </Text>
                  {brief && (
                    <Text size="sm" c="dimmed">
                      {brief}
                    </Text>
                  )}
                  {why && (
                    <Text size="sm" c="dimmed" mt={brief ? 4 : 0}>
                      {section ? `${section}: ` : ''}
                      {why}
                    </Text>
                  )}
                </Box>
              )}

              <Divider />

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
              <Group gap="xs" wrap="nowrap">
                <Button
                  size="compact-sm"
                  color={AI_COLOR}
                  leftSection={<Icon icon="mdi:refresh" width={14} />}
                  disabled={inert}
                  onClick={regenerate}
                  data-testid="draft-tile-regenerate-run"
                >
                  Regenerate
                </Button>
                {section && onRegenerateSection && (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color={AI_COLOR}
                    disabled={inert}
                    onClick={regenerateSection}
                    data-testid="draft-tile-regenerate-section"
                  >
                    Whole section
                  </Button>
                )}
              </Group>

              <Divider />

              <Group gap="xs" grow wrap="nowrap">
                <Button
                  size="compact-sm"
                  variant="light"
                  color="teal"
                  leftSection={<Icon icon="mdi:check" width={14} />}
                  disabled={inert}
                  onClick={keep}
                  data-testid="draft-tile-keep"
                >
                  {reviewed ? 'Reviewed - undo' : 'Keep'}
                </Button>
                <Button
                  size="compact-sm"
                  variant="subtle"
                  color="red"
                  leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                  disabled={inert}
                  onClick={remove}
                  data-testid="draft-tile-remove"
                >
                  Remove
                </Button>
              </Group>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      )}
    </Group>
  );
};

export default DraftTileActions;

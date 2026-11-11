/**
 * Empty states and the redaction note shared by the Tasks and Ingestion panes,
 * on the admin Log & Task tab and on the Activity page.
 */

import React from 'react';
import { Badge, Button, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

/** One active filter, shown as a chip in the empty state. */
export interface FilterChip {
  key: string;
  label: string;
}

/**
 * What an empty pane means: where its rows come from, so "nothing here" reads
 * as "nothing has happened yet" rather than "broken". When filters hide the
 * rows, they are listed as chips with a way to clear them instead.
 */
export const PaneEmptyState: React.FC<{
  /** Pane noun for the filtered message, e.g. "ingestion runs". */
  noun: string;
  /** Where the rows come from and how long they are kept. */
  source: React.ReactNode;
  chips?: FilterChip[];
  onClear?: () => void;
}> = ({ noun, source, chips = [], onClear }) => {
  if (chips.length > 0) {
    return (
      <Stack gap="xs" align="flex-start" data-testid="pane-empty-filtered">
        <Text size="xs" c="dimmed">
          No {noun} match these filters.
        </Text>
        <Group gap={6}>
          {chips.map((chip) => (
            <Badge key={chip.key} size="sm" variant="light" tt="none">
              {chip.label}
            </Badge>
          ))}
        </Group>
        {onClear && (
          <Button
            size="compact-xs"
            variant="light"
            leftSection={<Icon icon="mdi:filter-off-outline" width={14} />}
            onClick={onClear}
          >
            Clear filters
          </Button>
        )}
      </Stack>
    );
  }
  return (
    <Stack gap={4} data-testid="pane-empty">
      <Text size="xs" fw={500}>
        No {noun} recorded.
      </Text>
      <Text size="xs" c="dimmed">
        {source}
      </Text>
    </Stack>
  );
};

/** Shown in an open row whose details the reader's role does not include. */
export const RedactedNote: React.FC<{ what: string }> = ({ what }) => (
  <Text size="xs" c="dimmed" fs="italic" data-testid="redacted-note">
    {what} are visible to editors and owners of the project.
  </Text>
);

import React from 'react';
import { Badge, Group, Loader, Text } from '@mantine/core';

import type { ComponentDiff } from '../../api';
import { diffSummaryText } from '../../figureDiffOverlay';

/**
 * The legend chip of "Compare with last visit" (#1397): what changed, in
 * counts, or why this component cannot be compared. Renders nothing before
 * the diff is asked for.
 *
 * `matched` is how many of the diff's marks found a place in the figure; when
 * there are changes but none could be drawn, the chip says so and points at
 * the side-by-side view.
 */
const DiffSummaryChip: React.FC<{
  diff: ComponentDiff | null;
  loading?: boolean;
  error?: string | null;
  matched?: number;
  /** Float over the bottom-left of the tile, for tiles with no free row. */
  floating?: boolean;
}> = ({ diff, loading, error, matched, floating }) => {
  if (!diff && !loading && !error) return null;
  const style: React.CSSProperties = floating
    ? { position: 'absolute', left: 8, bottom: 6, zIndex: 5, maxWidth: 'calc(100% - 16px)' }
    : { flex: 'none' };

  let body: React.ReactNode;
  if (error) {
    body = (
      <Text size="xs" c="dimmed" data-testid="diff-unsupported">
        {error}
      </Text>
    );
  } else if (diff && diff.supported === false) {
    body = (
      <Text size="xs" c="dimmed" data-testid="diff-unsupported">
        {diff.reason}
      </Text>
    );
  } else if (diff) {
    const text = diffSummaryText(diff);
    const hasChanges = text ? !text.endsWith('no differences') : false;
    body = (
      <Group gap={6} wrap="nowrap">
        <Badge
          variant="light"
          size="sm"
          radius="sm"
          tt="none"
          style={{ maxWidth: '100%' }}
          data-testid="diff-summary"
        >
          {text}
        </Badge>
        {hasChanges && matched === 0 && (
          <Text size="xs" c="dimmed" data-testid="diff-undrawn">
            Not drawable on this figure, see Before | Now
          </Text>
        )}
      </Group>
    );
  } else {
    body = (
      <Group gap={6} wrap="nowrap" data-testid="diff-loading">
        <Loader size={12} />
        <Text size="xs" c="dimmed">
          Comparing with your last visit
        </Text>
      </Group>
    );
  }
  return (
    <div style={style} data-testid="diff-chip">
      {body}
    </div>
  );
};

export default DiffSummaryChip;

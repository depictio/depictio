import React from 'react';
import { Box, Group, Text } from '@mantine/core';

import type { ValueList } from './groupingGuide';

/**
 * The ids a group holds, as a list you can actually read.
 *
 * This replaces a wrapped row of six truncated badges. Sample ids are long and
 * differ in a suffix (`GM12878_OMNI_R1` vs `GM12878_STD_R1`), which is exactly
 * what a chip clips off, and a chip row reads across rather than down, so
 * comparing the ids meant re-parsing the row for every one. A monospace column
 * lines the shared prefix up and lets the eye run down the differences, which
 * is the only question being asked of this list: are these the samples I meant?
 *
 * Whole values, never truncated: a long id wraps to a second line rather than
 * losing the end that distinguishes it. The box scrolls at `rows`, so a
 * thousand-point lasso costs the same screen space as a five-point one.
 */
const ROW_PX = 19;

const ValueListPreview: React.FC<{
  values: ValueList;
  /** Rows visible before the box scrolls. */
  rows?: number;
  /** Shown above the list. Off on a saved group's card, where the card header
   *  already carries the count. */
  withHeader?: boolean;
}> = ({ values, rows = 5, withHeader = true }) => {
  if (values.distinct === 0) return null;

  return (
    <Box>
      {withHeader && (
        <Group gap={6} justify="space-between" wrap="nowrap" mb={4}>
          <Text size="xs" c="dimmed">
            {values.distinct.toLocaleString()} distinct value
            {values.distinct === 1 ? '' : 's'}
          </Text>
          {/* A lasso catches every point, and several points can be one
              sample. Saying so is the difference between "I picked 8" and
              "why does it say 34?". */}
          {values.total !== values.distinct && (
            <Text size="xs" c="dimmed">
              from {values.total.toLocaleString()} points
            </Text>
          )}
        </Group>
      )}
      <Box
        style={{
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-sm)',
          background: 'var(--mantine-color-default)',
          maxHeight: rows * ROW_PX + 8,
          overflowY: 'auto',
          padding: '4px 8px',
          // macOS overlay scrollbars paint over the last character otherwise.
          scrollbarGutter: 'stable',
        }}
      >
        {values.shown.map((v, i) => (
          // Index in the key: distinct values, but an empty string is a legal
          // value and React still wants the pair to be unique.
          <Text
            key={`${v}-${i}`}
            ff="monospace"
            size="xs"
            style={{ lineHeight: `${ROW_PX}px`, wordBreak: 'break-all' }}
          >
            {v}
          </Text>
        ))}
        {values.hidden > 0 && (
          <Text size="xs" c="dimmed" style={{ lineHeight: `${ROW_PX}px` }}>
            +{values.hidden.toLocaleString()} more
          </Text>
        )}
      </Box>
    </Box>
  );
};

export default ValueListPreview;

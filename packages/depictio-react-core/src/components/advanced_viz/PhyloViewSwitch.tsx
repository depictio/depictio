import React from 'react';
import { SegmentedControl, Stack, Text } from '@mantine/core';

import type { PhyloView } from './phylo/view';

/**
 * "Full tree | Summary by rank", first in the settings of both phylogenetic
 * renderers, so whichever one is on screen can hand over to the other.
 *
 * The switch only calls `view.setRank`; the router owns the state and decides
 * which renderer to mount from it (see phylo/view.ts). Where the summary cannot
 * be drawn the option stays visible but disabled, with the reason under it: a
 * control that silently does nothing reads as a broken one, and one that is
 * missing says nothing about how to get it.
 */
const PhyloViewSwitch: React.FC<{ view: PhyloView }> = ({ view }) => {
  const summary = view.rank != null;
  const blocked = !summary && view.blocker != null;
  return (
    <Stack gap={4}>
      <Text size="xs" fw={500}>
        View
      </Text>
      <SegmentedControl
        size="xs"
        fullWidth
        value={summary ? 'summary' : 'tree'}
        onChange={(v) => view.setRank(v === 'summary' ? view.summaryRank : null)}
        data={[
          { value: 'tree', label: 'Full tree' },
          { value: 'summary', label: 'Summary by rank', disabled: blocked },
        ]}
        data-testid="phylo-view-switch"
      />
      {blocked ? (
        <Text size="xs" c="dimmed">
          {view.blocker}
        </Text>
      ) : null}
    </Stack>
  );
};

export default PhyloViewSwitch;

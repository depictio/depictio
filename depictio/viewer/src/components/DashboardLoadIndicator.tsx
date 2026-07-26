import React from 'react';
import { Group, RingProgress, Stack, Text, Tooltip, Transition } from '@mantine/core';
import { useDashboardLoadSummary } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

interface DashboardLoadIndicatorProps {
  /** The panels rendered in the grid (cards + data components). */
  metadataList: StoredMetadata[];
  /** True while the card bulk-compute round-trip is in flight. */
  cardsLoading: boolean;
}

/**
 * Ring + count shown beside the dashboard title while panels are loading, with
 * a hover tooltip breaking the numbers down. Fades out once everything in view
 * is ready.
 *
 * Sits in the header rather than as a full-width strip under it: the count is
 * scoped to the viewport, so scrolling new panels in makes the indicator come
 * back repeatedly, and a line flashing across the whole page each time reads as
 * an error. A ring in the title row carries the same information without the
 * page-level interruption, and needs no fixed positioning.
 *
 * The filled arc is ``ready / in view``, not ``ready / whole dashboard`` — see
 * ``useDashboardLoadSummary``. So it does reach 100%, and the denominator grows
 * as you scroll; the tooltip names the off-screen remainder so the scoping is
 * legible.
 */
const DashboardLoadIndicator: React.FC<DashboardLoadIndicatorProps> = ({
  metadataList,
  cardsLoading,
}) => {
  const { ready, loading, error, deferred, total, fraction } = useDashboardLoadSummary(
    metadataList,
    cardsLoading,
  );

  // Nothing in view is loading, or everything in view finished cleanly.
  const settled = total === 0 || (ready === total && error === 0);

  const label = (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        {ready} / {total} panels in view ready
      </Text>
      {loading > 0 && (
        <Text size="xs" c="dimmed">
          {loading} loading…
        </Text>
      )}
      {deferred > 0 && (
        <Text size="xs" c="dimmed">
          {deferred} further down — not counted until scrolled into view
        </Text>
      )}
      {error > 0 && (
        <Text size="xs" c="red">
          {error} failed
        </Text>
      )}
    </Stack>
  );

  return (
    <Transition mounted={!settled} transition="fade" duration={200} timingFunction="ease">
      {(transitionStyle) => (
        <Tooltip label={label} withArrow openDelay={0} multiline position="bottom">
          <Group
            gap={5}
            wrap="nowrap"
            style={transitionStyle}
            data-tour-id="dashboard-load-indicator"
            role="progressbar"
            aria-valuenow={ready}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-label={`${ready} of ${total} panels in view loaded`}
          >
            <RingProgress
              size={26}
              thickness={4}
              rootColor="var(--mantine-color-default-border)"
              sections={[
                { value: fraction * 100, color: 'var(--mantine-primary-color-filled)' },
                // Failures take their own arc rather than silently shrinking the
                // track, so a partly-broken dashboard doesn't read as "still busy".
                { value: total > 0 ? (error / total) * 100 : 0, color: 'var(--mantine-color-red-6)' },
              ]}
            />
            {/* Tabular figures so the count doesn't jitter as digits change. */}
            <Text size="sm" c="dimmed" fw={500} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {ready}/{total}
            </Text>
          </Group>
        </Tooltip>
      )}
    </Transition>
  );
};

export default DashboardLoadIndicator;

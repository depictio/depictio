import React from 'react';
import { Tooltip, Stack, Text } from '@mantine/core';
import { useDashboardLoadSummary } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

interface DashboardLoadingBarProps {
  /** The panels rendered in the grid (cards + data components). */
  metadataList: StoredMetadata[];
  /** True while the card bulk-compute round-trip is in flight. */
  cardsLoading: boolean;
}

/**
 * Determinate progress bar pinned under the header. Reads the dashboard load
 * registry and shows ``ready / total`` panels, with a hover tooltip breaking
 * the count down. Auto-hides once everything tracked is ready.
 *
 * Rendered as a custom gradient bar (not Mantine ``Progress``) so it can carry
 * a smooth width transition, a leading-edge glow and a glossy sheen while
 * actively loading — see the ``.depictio-loading-bar*`` rules in app.css. All
 * colours resolve from Mantine tokens, so it tracks light/dark.
 *
 * The fraction can legitimately plateau below 100%: off-screen panels defer
 * their fetch until scrolled into view (``useInView``), so they sit in
 * ``pending``. The tooltip says so explicitly rather than letting a stalled bar
 * read as broken.
 */
const DashboardLoadingBar: React.FC<DashboardLoadingBarProps> = ({
  metadataList,
  cardsLoading,
}) => {
  const { ready, loading, error, pending, total, fraction } = useDashboardLoadSummary(
    metadataList,
    cardsLoading,
  );

  // Nothing to track, or everything finished cleanly → no bar.
  if (total === 0 || (ready === total && error === 0)) return null;

  const label = (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        {ready} / {total} panels ready
      </Text>
      {loading > 0 && (
        <Text size="xs" c="dimmed">
          {loading} loading…
        </Text>
      )}
      {pending > 0 && (
        <Text size="xs" c="dimmed">
          {pending} waiting to scroll into view
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
    <div
      className="depictio-loading-bar"
      data-loading={loading > 0}
      data-error={error > 0}
      data-tour-id="dashboard-loading-bar"
    >
      <Tooltip label={label} position="bottom" withArrow openDelay={0} multiline>
        <div
          className="depictio-loading-bar__track"
          role="progressbar"
          aria-valuenow={ready}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${ready} of ${total} panels loaded`}
        >
          <div
            className="depictio-loading-bar__fill"
            style={{ width: `${Math.round(fraction * 100)}%` }}
          />
        </div>
      </Tooltip>
    </div>
  );
};

export default DashboardLoadingBar;

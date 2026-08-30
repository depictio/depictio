import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** Reported by figure / table renderers so the chrome can offer a "load
 *  everything" toggle consistently across component types. ``null`` (no state)
 *  means the component isn't reduced and has nothing to expand. */
export interface LoadAllState {
  /** Currently showing a reduced view (sampled figure / paginated table). */
  reduced: boolean;
  /** Currently showing the full, uncapped view. */
  full: boolean;
  /** A full-load fetch is in flight. */
  loading: boolean;
  /** Flip between the reduced and full views. */
  toggle: () => void;
  /** Noun for the tooltip — "points" (figure) or "rows" (table). */
  noun: string;
}

/**
 * Chrome action icon that toggles a component between its reduced view
 * (downsampled figure / paginated table) and a full load of every point / row.
 * Rendered in the same hover-revealed action cluster as reset / fullscreen /
 * download so the affordance is consistent across component types.
 */
const LoadAllButton: React.FC<{ state: LoadAllState }> = ({ state }) => {
  const label = state.full
    ? `Back to reduced view`
    : `Load all ${state.noun} (may be slow on large datasets)`;
  return (
    <Tooltip label={label} withArrow>
      <ActionIcon
        variant={state.full ? 'filled' : 'subtle'}
        color="gray"
        size="sm"
        loading={state.loading}
        onClick={state.toggle}
        aria-label={state.full ? 'Back to reduced view' : `Load all ${state.noun}`}
      >
        <Icon
          icon={state.full ? 'mdi:arrow-collapse-vertical' : 'mdi:database-arrow-down'}
          width={16}
          height={16}
        />
      </ActionIcon>
    </Tooltip>
  );
};

export default LoadAllButton;

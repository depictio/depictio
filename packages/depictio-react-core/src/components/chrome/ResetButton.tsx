import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface ResetButtonProps {
  onResetFilter?: () => void;
  /** When true, this component is the SOURCE of an active dashboard filter —
   *  render the icon in its "active" style (filled orange) instead of the
   *  inactive light variant. */
  active?: boolean;
}

/**
 * Clears the filter contributed by THIS interactive component, mirroring the
 * "reset" semantics in `depictio/dash/modules/shared/selection_utils.py:58-97`
 * — caller provides the actual reset callback (typically `onChange(null)`).
 *
 * Always rendered in the chrome row to preserve action-icon order; styling
 * switches between filled (active filter) and light (idle) so users can tell
 * at a glance whether a filter is currently sourced from this component.
 */
const ResetButton: React.FC<ResetButtonProps> = ({ onResetFilter, active = false }) => {
  const disabled = !onResetFilter || !active;
  return (
    <Tooltip
      label={active ? 'Reset filter from this component' : 'Reset selection'}
      withArrow
    >
      <ActionIcon
        variant={active ? 'filled' : 'light'}
        color="orange"
        size="sm"
        disabled={disabled}
        onClick={() => onResetFilter?.()}
        aria-label="Reset selection"
      >
        <Icon icon="bx:reset" width={16} height={16} />
      </ActionIcon>
    </Tooltip>
  );
};

export default ResetButton;

import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface ResetButtonProps {
  onResetFilter?: () => void;
}

/**
 * Clears the filter contributed by THIS interactive component, mirroring the
 * "reset" semantics in `depictio/dash/modules/shared/selection_utils.py:58-97`
 * — caller provides the actual reset callback (typically `onChange(null)`).
 */
const ResetButton: React.FC<ResetButtonProps> = ({ onResetFilter }) => {
  const disabled = !onResetFilter;
  return (
    <Tooltip label="Reset selection" withArrow>
      <ActionIcon
        variant="light"
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

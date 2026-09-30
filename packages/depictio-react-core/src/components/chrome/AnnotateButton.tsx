import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface AnnotateButtonProps {
  active: boolean;
  onToggle: () => void;
}

/**
 * Toggles annotate mode on a figure: drag a range, click a line or a note,
 * lasso points. Only rendered when the app's annotation layer lets the user
 * annotate (editors and owners).
 */
const AnnotateButton: React.FC<AnnotateButtonProps> = ({ active, onToggle }) => {
  const label = active ? 'Leave annotate mode' : 'Annotate';
  return (
    <Tooltip label={label} withArrow>
      <ActionIcon
        variant={active ? 'filled' : 'subtle'}
        color="blue"
        size="sm"
        onClick={onToggle}
        aria-label={label}
        aria-pressed={active}
        data-testid="annotate-button"
      >
        <Icon icon="mdi:draw" width={16} height={16} />
      </ActionIcon>
    </Tooltip>
  );
};

export default AnnotateButton;

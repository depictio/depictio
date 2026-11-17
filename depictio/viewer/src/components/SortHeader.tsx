import React from 'react';
import { Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

export type SortDir = 'asc' | 'desc';

export interface SortHeaderProps {
  label: string;
  ariaLabel?: string;
  tooltip?: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}

/** A clickable table column header showing the current sort direction. */
const SortHeader: React.FC<SortHeaderProps> = ({
  label,
  ariaLabel,
  tooltip,
  active,
  dir,
  onClick,
}) => {
  const button = (
    <UnstyledButton
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontWeight: 600,
      }}
      aria-label={`Sort by ${ariaLabel ?? tooltip ?? label}`}
    >
      {label}
      <Icon
        icon={
          active
            ? dir === 'asc'
              ? 'mdi:chevron-up'
              : 'mdi:chevron-down'
            : 'mdi:unfold-more-horizontal'
        }
        width={14}
        style={{ opacity: active ? 1 : 0.4 }}
      />
    </UnstyledButton>
  );
  return tooltip ? (
    <Tooltip label={tooltip} withinPortal>
      {button}
    </Tooltip>
  ) : (
    button
  );
};

export default SortHeader;

import React from 'react';
import { ActionIcon, Popover, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { CatalogSource } from '../../api';
import CatalogOrigin from './CatalogOrigin';

/**
 * Chrome action marking a component that came from the tools catalog.
 *
 * It lives in the action cluster rather than as a badge pinned over the tile:
 * a badge at top-left sits exactly where a component draws its title, so it
 * covered the title on every figure. Here it inherits the cluster's behaviour
 * (revealed on hover, opaque backing, already stacked above Plotly's modebar),
 * costing nothing at rest. The provenance itself moves one click away, which is
 * where it belongs — it is reference material, not something to read at a glance.
 */
const CatalogButton: React.FC<{ source: CatalogSource }> = ({ source }) => (
  <Popover position="bottom-end" withArrow shadow="md" width={340}>
    <Popover.Target>
      <Tooltip
        label={source.toolName ? `From catalog · ${source.toolName}` : 'From the tools catalog'}
        withArrow
      >
        <ActionIcon variant="light" color="violet" size="sm" aria-label="Catalog origin">
          <Icon icon="mdi:toolbox-outline" width={16} height={16} />
        </ActionIcon>
      </Tooltip>
    </Popover.Target>
    <Popover.Dropdown p="sm">
      <CatalogOrigin source={source} framed={false} />
    </Popover.Dropdown>
  </Popover>
);

export default CatalogButton;

import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { CatalogSource } from '../../api';

/**
 * Always-visible "from catalog" flag pinned to the top-left of a component tile.
 * Marks components that were added from the depictio tools catalog, in the
 * catalog's violet accent. Full provenance (tool / output / `use:` snippet) is
 * in the metadata inspector; this is just the at-a-glance badge.
 *
 * Uses an Iconify toolbox glyph rather than the raster tools-catalog logo so the
 * shared package carries no viewer-only asset path (the logo lives on the
 * viewer's ChoiceScreen, served under /dashboard/).
 */
const CatalogFlag: React.FC<{ source: CatalogSource }> = ({ source }) => {
  const label = source.toolName
    ? `From catalog · ${source.toolName}`
    : 'From the tools catalog';
  return (
    <Tooltip label={label} withArrow position="right">
      <Badge
        className="depictio-catalog-flag"
        color="violet"
        variant="light"
        size="xs"
        radius="sm"
        leftSection={<Icon icon="mdi:toolbox-outline" width={11} />}
        styles={{ root: { textTransform: 'none', cursor: 'default' } }}
      >
        Catalog
      </Badge>
    </Tooltip>
  );
};

export default CatalogFlag;

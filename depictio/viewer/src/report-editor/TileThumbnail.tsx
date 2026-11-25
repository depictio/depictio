import React from 'react';
import { Box } from '@mantine/core';

import EnlargedTile from './tiles/EnlargedTile';
import TileRender from './tiles/TileRender';

interface TileThumbnailProps {
  tileKey: string;
  tabId: string;
  componentId: string;
  title: string;
  componentType: string | null | undefined;
  /** The frame's PNG of a Plotly figure, when it has sent one. */
  png: string | undefined;
  /** Shown at full size: the card's enlarge button, or a double click. */
  large: boolean;
  onLargeChange: (open: boolean) => void;
}

/** A tile's render of its component (the real renderer, see `tiles/`). A
 *  click selects the tile, like a click anywhere on its card; a double click
 *  opens it at full size. */
const TileThumbnail: React.FC<TileThumbnailProps> = ({
  tileKey,
  tabId,
  componentId,
  title,
  componentType,
  png,
  large,
  onLargeChange,
}) => {
  return (
    <>
      <Box
        data-testid={`report-thumbnail-${tileKey}`}
        onDoubleClick={(e: React.MouseEvent) => {
          e.stopPropagation();
          onLargeChange(true);
        }}
      >
        <TileRender
          tileKey={tileKey}
          tabId={tabId}
          componentId={componentId}
          componentType={componentType}
          png={png}
        />
      </Box>
      {/* Only mounted once asked for: a closed modal costs nothing. */}
      {large && (
        <EnlargedTile
          opened={large}
          onClose={() => onLargeChange(false)}
          tileKey={tileKey}
          tabId={tabId}
          componentId={componentId}
          title={title}
          componentType={componentType}
          png={png}
        />
      )}
    </>
  );
};

export default TileThumbnail;

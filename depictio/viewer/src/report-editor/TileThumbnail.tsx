import React, { useState } from 'react';
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
}

/** A tile's render of its component (the real renderer, see `tiles/`), with a
 *  click that opens it at full size. */
const TileThumbnail: React.FC<TileThumbnailProps> = ({
  tileKey,
  tabId,
  componentId,
  title,
  componentType,
  png,
}) => {
  const [large, setLarge] = useState(false);
  return (
    <>
      <Box
        role="button"
        tabIndex={0}
        aria-label={`Enlarge ${title}`}
        data-testid={`report-thumbnail-${tileKey}`}
        onClick={(e: React.MouseEvent) => {
          e.stopPropagation();
          setLarge(true);
        }}
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            e.stopPropagation();
            setLarge(true);
          }
        }}
        style={{ cursor: 'zoom-in' }}
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
          onClose={() => setLarge(false)}
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

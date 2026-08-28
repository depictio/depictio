import React from 'react';

import { useColorScheme } from '../hooks/useColorScheme';

/**
 * The depictio wordmark, themed.
 *
 * `logo_black.svg` and `logo_white.svg` are byte-identical (a base64 raster
 * inside an SVG wrapper), so swapping `src` does nothing. Dark mode inverts the
 * embedded raster with a filter and rotates the hue back to keep the brand
 * colours, which is the standard treatment for a single-asset wordmark.
 */
const DepictioLogo: React.FC<{ height?: number }> = ({ height = 20 }) => {
  const { colorScheme } = useColorScheme();

  return (
    <img
      src="/dashboard/logos/logo_black.svg"
      alt="Depictio"
      style={{
        height,
        width: 'auto',
        display: 'block',
        filter: colorScheme === 'dark' ? 'invert(1) hue-rotate(180deg)' : undefined,
      }}
    />
  );
};

export default DepictioLogo;

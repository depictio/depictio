import React from 'react';
import { useIsStaticBundle } from 'depictio-react-core';

import { useColorScheme } from '../hooks/useColorScheme';
// Bundled copy of public/logos/logo_black.svg. Static bundles open from
// file:// where the server-served `/dashboard/logos/...` path can't resolve;
// importing the asset lets Vite inline it (vite.static.config.ts sets
// `assetsInlineLimit` high enough that the single-file build embeds it as a
// data: URI). Server builds keep the original absolute path so the SVG stays
// separately cacheable.
import inlineLogo from '../assets/depictio_logo.svg';

interface DepictioLogoProps {
  /** Rendered height in px; width follows the aspect ratio. */
  height?: number;
}

/**
 * The Depictio wordmark, themed. Shared by the header's "Powered by" badge and
 * the sidebar footer so the file:// fallback and the dark-mode treatment have
 * one implementation instead of one per call site.
 *
 * `logo_black.svg` and `logo_white.svg` are byte-identical (a base64-embedded
 * PNG inside an SVG wrapper), so swapping `src` by theme does nothing. A CSS
 * filter inverts the embedded raster on dark while preserving brand hues — the
 * standard treatment for a single-asset wordmark.
 */
const DepictioLogo: React.FC<DepictioLogoProps> = ({ height = 20 }) => {
  const { colorScheme } = useColorScheme();
  const isStaticBundle = useIsStaticBundle();

  return (
    <img
      src={isStaticBundle ? inlineLogo : '/dashboard/logos/logo_black.svg'}
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

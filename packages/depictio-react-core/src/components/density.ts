import React from 'react';

/**
 * How much room a tile's furniture may take. A section that packs linked views
 * into one screen (`display: linked`) provides `compact`; a tile reading it
 * keeps its title row to one line and moves secondary text into tooltips.
 * Everything else renders `normal`.
 */
export type Density = 'normal' | 'compact';

export const DensityContext = React.createContext<Density>('normal');

export function useDensity(): Density {
  return React.useContext(DensityContext);
}

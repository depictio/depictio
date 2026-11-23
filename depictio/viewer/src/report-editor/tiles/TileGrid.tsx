import React from 'react';

import './tiles.css';

/** The grid the tiles of a section (or of a tab, outside any section) sit in.
 *  Its children are full-row unless they carry `rpt-tile--half`. */
const TileGrid: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="rpt-grid" data-testid="report-tile-grid">
    {children}
  </div>
);

export default TileGrid;

import React from 'react';

import './pages.css';

/** A run of icon keys sharing one frosted tray under Glass. With any other
 *  chrome it draws no box (`display: contents`), so the keys lay out as they
 *  always did. */
const GlassTray: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="gp-tray">{children}</div>
);

export default GlassTray;

import { Icon } from '@iconify/react';
import React from 'react';

import './panelAccents.css';

/**
 * Header of the two right-hand panels (Analysis, Metadata): a tile in the
 * panel's colour, its name over a one-line purpose, and a count pill. Colours
 * come from the enclosing `.dc-panel--*` class, so the title cannot disagree
 * with the dock button that opens the panel.
 */
export const PanelTitle: React.FC<{
  icon: string;
  title: string;
  subtitle: string;
  count?: string | null;
}> = ({ icon, title, subtitle, count }) => (
  <div className="dc-ph">
    <span className="dc-ph-tile" aria-hidden>
      <Icon icon={icon} width={20} height={20} />
    </span>
    <span className="dc-ph-text">
      <span className="dc-ph-name">{title}</span>
      <span className="dc-ph-sub">{subtitle}</span>
    </span>
    {count ? <span className="dc-ph-pill">{count}</span> : null}
  </div>
);

export default PanelTitle;

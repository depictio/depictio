import React from 'react';
import { Icon } from '@iconify/react';

/** Each step's glyph, shared by its page head and the start screen's tiles. */
export const STEP_ICONS = [
  'mdi:tools',
  'mdi:file-delimited-outline',
  'mdi:chart-box-outline',
  'mdi:download',
] as const;

/**
 * A step's page head, in depictio's page-head pattern (`gp-head` in
 * chrome/variants/glass/pages/pages.css, as the Projects and Dashboards pages
 * and the component builder draw it): an icon tile in the section's tone, the
 * title, one dimmed line on what the step is for, and the step's own actions
 * on the right.
 */
export default function StepHead({
  step,
  title,
  description,
  actions,
}: {
  step: number;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="gp-head bgl-head">
      <span className="gp-head-icon bgl-head-icon" aria-hidden>
        <Icon icon={STEP_ICONS[step]} width={24} />
      </span>
      <div className="gp-head-text">
        <h1 className="gp-title">{title}</h1>
        {description && <p className="gp-desc">{description}</p>}
      </div>
      {actions && <div className="gp-head-actions">{actions}</div>}
    </div>
  );
}

import React from 'react';
import { Alert } from '@mantine/core';
import { Icon } from '@iconify/react';

interface DemoModeBannerProps {
  /** Optional override for the banner copy. */
  message?: string;
}

/** Fixed-position banner shown at the top of viewer / editor / dashboards
 *  pages when the backend reports ``is_demo_mode === true``. Mirrors what the
 *  Dash app would have surfaced in the same situation. */
const DemoModeBanner: React.FC<DemoModeBannerProps> = ({ message }) => (
  <Alert
    color="yellow"
    variant="filled"
    radius={0}
    icon={<Icon icon="mdi:information" width={16} height={16} />}
    style={{
      position: 'sticky',
      top: 0,
      zIndex: 200,
    }}
  >
    {message ?? "Demo mode — your changes won't be saved."}
  </Alert>
);

export default DemoModeBanner;

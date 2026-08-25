import React from 'react';
import { Anchor, Tooltip } from '@mantine/core';

import DepictioLogo from './DepictioLogo';

/**
 * The depictio mark, as app identity rather than as a credit.
 *
 * The component builder routes (`/component/add/{id}`, `/component/edit/{id}`)
 * replace the whole AppShell, so they drop the editor's header, its sidebar and
 * the "Powered by" badge with them. That left the deepest screens in the product
 * as the only ones carrying no sign of which product they belong to.
 *
 * `PoweredBy` is deliberately not reused: it reads "Powered by" and links out to
 * the docs site, which is the wrong register for a mark whose job is to say
 * where you are and take you home.
 */
const BrandMark: React.FC = () => (
  <Tooltip label="Back to dashboards" withArrow>
    <Anchor href="/dashboards" underline="never" style={{ display: 'flex', flexShrink: 0 }}>
      <DepictioLogo height={22} />
    </Anchor>
  </Tooltip>
);

export default BrandMark;

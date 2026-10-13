import React from 'react';

import DepictioRose from './rose/DepictioRose';

/**
 * The Depictio mark as a loading indicator, used for the two boot states that
 * genuinely have no progress to report:
 *
 *  - `main.tsx`: the lazy route chunk is still downloading, so the app shell
 *    doesn't exist yet.
 *  - `App.tsx`: the dashboard document is in flight, so the panel list (and
 *    with it anything the header's `DashboardLoadIndicator` could count) is
 *    not known.
 *
 * Neither phase can show a fraction, so a spinner is the honest signal; it may
 * as well be the brand mark rather than a generic one. The rose's `loading`
 * mode never rests on the logo shape, so it reads as busy, and the element
 * carries its own `role="status"` label and reduced-motion fallback.
 *
 * Fixed and viewport-centred rather than laid out in flow: both phases render
 * it at the same screen position, so crossing from one to the other leaves the
 * mark where it is instead of making it jump. See `.depictio-boot-splash` in
 * app.css.
 */
const BootSplash: React.FC = () => (
  <div className="depictio-boot-splash">
    <DepictioRose mode="loading" size={96} />
  </div>
);

export default BootSplash;

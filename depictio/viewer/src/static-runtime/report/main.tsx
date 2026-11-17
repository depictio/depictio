/**
 * Entry of the report runtime: the static runtime, hosted by a Quarto report.
 *
 * The host itself is `boot.tsx` (shared with the combined runtime); this entry
 * adds the stylesheets, which `vite.report.config.ts` scopes to the runtime's
 * own roots at build time, and boots once the document is parsed.
 */
import '../../icons';

import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../../styles/app.css';
// The Paper keys and strips (`.hy-key`, the filter strip): the bundle gets
// them through the glass Shell, which a report does not mount.
import '../../chrome/variants/glass/layout.css';
import './report.css';

import { bootReport } from './boot';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => bootReport(), { once: true });
} else {
  bootReport();
}

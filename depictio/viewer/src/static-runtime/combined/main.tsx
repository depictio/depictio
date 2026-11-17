/**
 * Entry of the combined runtime: ONE script for both views of a combined
 * report + dashboard file (`vite.combined.config.ts`).
 *
 * It runs twice, in two documents of the same file:
 *
 *   - in the report (the page, a rendered Quarto document holding
 *     `#depictio-report-manifest`): it scopes its own stylesheet onto the
 *     runtime's roots, mounts the report's tiles and filter panel (the report
 *     host, `report/boot.tsx`) and installs the switch, the cross-links and the
 *     deep links (`host.ts`);
 *   - in the dashboard (the iframe `host.ts` writes on demand, holding
 *     `#bundle-manifest` and `#root`): it mounts the whole viewer App (the
 *     bundle host, `appHost.tsx`), opened on the tab asked for and sharing the
 *     report's filter state.
 *
 * It also stands in for the report's own copy of Plotly: the export's static
 * figures call `window.Plotly.newPlot` while the page parses, so the producer
 * drops Quarto's plotly.js and puts this script where it was.
 */
import '../../icons';

import Plotly from 'plotly.js';

import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/carousel/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/tiptap/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../../styles/app.css';
// The report host's own: the Paper keys and strips, and the placeholders.
import '../../chrome/variants/glass/layout.css';
import '../report/report.css';

import {
  REPORT_MANIFEST_ID,
  createFilterChannel,
  findCombinedHost,
} from 'depictio-static-core';

import { bootApp } from '../appHost';
import { bootReport } from '../report/boot';
import { RUNTIME_ATTR, installCombinedHost, readCombinedConfig } from './host';
import { adoptScopedStyles } from './scopeStyles';
import { withReachableBasemap } from '../mapBasemap';

declare global {
  interface Window {
    Plotly?: unknown;
  }
}

/** The class every root of the report host carries (report/boot.tsx). */
const REPORT_ROOT = '.depictio-report-root';

/**
 * The report's static figures call `window.Plotly.newPlot` while the page
 * parses. A map among them (Quarto's own drawing of a map tile, kept as the
 * tile's fallback) asks MapLibre for its network basemap, and offline that
 * throws `Map error.` as an uncaught page error. They go through the same
 * reachability check the runtime's own maps do: the basemap when it loads, a
 * blank style otherwise.
 */
function offlineSafePlotly(lib: typeof Plotly): typeof Plotly {
  const newPlot = lib.newPlot.bind(lib) as (...args: unknown[]) => Promise<unknown>;
  const wrapped = (gd: unknown, data?: unknown, layout?: unknown, config?: unknown) => {
    const figure = { data: data as unknown[], layout: layout as Record<string, unknown> };
    return withReachableBasemap({ figure }, 'light', { retheme: false }).then((safe) =>
      newPlot(gd, safe.figure?.data, safe.figure?.layout, config),
    );
  };
  return Object.assign(Object.create(lib) as typeof Plotly, { newPlot: wrapped });
}

if (!window.Plotly) window.Plotly = offlineSafePlotly(Plotly);

function bootDashboardView(): void {
  const host = findCombinedHost(window);
  bootApp({
    initialTab: host?.requestedTab?.() ?? null,
    onController: (controller) => host?.attachDashboard?.(controller),
  });
}

function bootReportView(): void {
  const css = document.querySelector(`script[${RUNTIME_ATTR}="css"]`)?.textContent ?? '';
  if (css) {
    try {
      // Virgil is the app's hand-drawn page-title face; no tile draws in it.
      adoptScopedStyles(document, css, REPORT_ROOT, { dropFontFaces: ['Virgil'] });
    } catch (err) {
      console.warn('[depictio] the runtime stylesheet could not be applied', err);
    }
  }
  const channel = createFilterChannel();
  const booted = bootReport({ channel });
  if (!booted) return;
  installCombinedHost({ manifest: booted.manifest, channel, config: readCombinedConfig() });
}

if (document.getElementById('bundle-manifest') && document.getElementById('root')) {
  bootDashboardView();
} else if (document.readyState === 'loading') {
  document.addEventListener(
    'DOMContentLoaded',
    () => {
      if (document.getElementById(REPORT_MANIFEST_ID)) bootReportView();
    },
    { once: true },
  );
} else if (document.getElementById(REPORT_MANIFEST_ID)) {
  bootReportView();
}

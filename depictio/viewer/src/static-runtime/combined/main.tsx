/**
 * Entry of the static runtime a rendered report embeds: ONE script for both
 * outputs of a report (`vite.combined.config.ts`), the report alone and the
 * combined report + dashboard file.
 *
 * In the report (the page, a rendered Quarto document holding
 * `#depictio-report-manifest`) it scopes its own stylesheet onto the
 * runtime's roots and mounts the report's tiles and filter panels (the report
 * host, `report/boot.tsx`). The report's config says which output the file
 * is: with a `combined` section it also installs the "Report | Dashboard"
 * switch, the cross-links and the deep links (`host.ts`); without one (the
 * report-only output) it stops there: no switch, no dashboard, no frame.
 *
 * In the dashboard (a serverless bundle page, or the iframe `host.ts` writes
 * on demand, holding `#bundle-manifest` and `#root`) it mounts the whole viewer App (the bundle
 * host, `appHost.tsx`), opened on the tab asked for and sharing the report's
 * filter state.
 *
 * It also stands in for the report's own copy of Plotly: the export's static
 * figures call `window.Plotly.newPlot` while the page parses, so the producer
 * drops Quarto's plotly.js and puts this script where it was.
 */
import '../../icons';

import Plotly from 'plotly.js';

import '../appStyles';
// The report host's own, after the App's: the Paper keys and strips, and the
// placeholders.
import '../../chrome/variants/glass/layout.css';
import '../report/report.css';

import {
  BUNDLE_MANIFEST_ID,
  REPORT_MANIFEST_ID,
  createFilterChannel,
  findCombinedHost,
} from 'depictio-static-core';

import { bootApp } from '../appHost';
import { bootReport } from '../report/boot';
import { readReportConfig } from '../report/page';
import { RUNTIME_ATTR, installCombinedHost } from './host';
import { injectScopedStyles } from './scopeStyles';
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
      injectScopedStyles(document, css, REPORT_ROOT, { dropFontFaces: ['Virgil'] });
    } catch (err) {
      console.warn('[depictio] the runtime stylesheet could not be applied', err);
    }
  }
  const combined = readReportConfig().combined;
  if (!combined) {
    // The report alone: its tiles and its filter panel, nothing else.
    bootReport();
    return;
  }
  const channel = createFilterChannel();
  const booted = bootReport({ channel });
  if (!booted) return;
  installCombinedHost({ manifest: booted.manifest, channel, config: combined });
}

if (document.getElementById(BUNDLE_MANIFEST_ID) && document.getElementById('root')) {
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

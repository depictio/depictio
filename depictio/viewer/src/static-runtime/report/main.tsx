/**
 * Entry of the report runtime: the static runtime, hosted by a Quarto report.
 *
 * The serverless bundle and the report share one manifest contract
 * (`depictio/models/models/serverless.py`, built by producer A) and one
 * runtime (the shims of `vite-plugins/static-runtime.ts`, the engine of
 * `depictio-static-core`, the renderers of `depictio-react-core`). They differ
 * only in the host: the bundle mounts the viewer App over a whole page; the
 * report mounts each tile into the place the export gave it in the document
 * (`<div data-depictio-tile="<tab_id>:<index>">`), and the dashboard's
 * controls into the report's "Filters" part (`<div data-depictio-filters>`).
 *
 * The page is someone else's: Quarto's Bootstrap, its fonts, its layout. So
 * nothing here styles the page. The runtime's CSS is scoped to its own roots
 * at build time (`vite-plugins/scope-css.ts`); Mantine's variables are written
 * for those roots only (`cssVariablesSelector`), and its portals land in a root
 * of their own at the end of <body>. Inter is already in the report (the
 * Quarto theme embeds it); this build carries no font of its own.
 *
 * Zero network, as the bundle: every api.ts call is shimmed.
 */
import '../../icons';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider, Portal, mergeThemeOverrides, createTheme } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../../styles/app.css';
// The Paper keys and strips (`.hy-key`, the filter strip): the bundle gets
// them through the glass Shell, which a report does not mount.
import '../../chrome/variants/glass/layout.css';
import './report.css';

import {
  BrandingContext,
  StaticBadgeProvider,
  buildDepictioTheme,
  setChromeStyle,
  type BrandTheme,
  type StaticTierMap,
} from 'depictio-react-core';
import {
  REPORT_CONFIG_ID,
  REPORT_FILTERS_ATTR,
  REPORT_MANIFEST_ID,
  REPORT_TILE_ATTR,
  groupMountVerdict,
  parseTileRefs,
} from 'depictio-static-core';

import paper from '../../chrome/variants/glass/glass';
import { installInlineMultiqcLogos } from '../../chrome/multiqcLogo';
import { loadBundleFromDocument, setActiveTab } from '../bundle';
import ReportRuntime, { type ReportPanel, type ReportTile } from './ReportRuntime';

/** The class every root of the runtime carries: what its CSS is scoped to. */
const ROOT_CLASS = 'depictio-report-root';

interface ReportConfig {
  /** The report's brand: its primary colour and font, so a tile's accent is
   *  the document's. */
  brand?: BrandTheme | null;
}

function readConfig(): ReportConfig {
  try {
    const raw = document.getElementById(REPORT_CONFIG_ID)?.textContent;
    return raw ? (JSON.parse(raw) as ReportConfig) : {};
  } catch {
    return {};
  }
}

/** A root of the runtime: the class its scoped CSS keys on, Paper, light. */
function runtimeRoot(extraClass: string): HTMLDivElement {
  const el = document.createElement('div');
  el.className = `${ROOT_CLASS} ${extraClass}`;
  el.dataset.chrome = paper.id;
  el.setAttribute('data-mantine-color-scheme', 'light');
  return el;
}

function boot(): void {
  if (!document.getElementById(REPORT_MANIFEST_ID)) return;
  let manifest;
  try {
    manifest = loadBundleFromDocument(REPORT_MANIFEST_ID);
  } catch (err) {
    // A manifest the runtime cannot read leaves every fallback in place.
    console.warn('[depictio report] manifest unreadable; the report keeps its own output', err);
    return;
  }
  setActiveTab(manifest.dashboard.id);
  // The renderers style their figures through the active chrome (glassPlotly).
  setChromeStyle(paper);
  // file:// cannot reach `/dashboard/logos/...`: MultiQC tab icons use the
  // inlined copies instead.
  installInlineMultiqcLogos();

  const tiles: ReportTile[] = [];
  for (const host of Array.from(document.querySelectorAll<HTMLElement>(`[${REPORT_TILE_ATTR}]`))) {
    const refs = parseTileRefs(host.getAttribute(REPORT_TILE_ATTR));
    const verdict = groupMountVerdict(manifest, refs);
    if (!verdict.mount) {
      host.dataset.depictioFallbackReason = verdict.reason;
      continue;
    }
    const mount = runtimeRoot('depictio-report-mount');
    host.appendChild(mount);
    tiles.push({ host, mount, refs });
  }
  const panels: ReportPanel[] = [];
  for (const host of Array.from(
    document.querySelectorAll<HTMLElement>(`[${REPORT_FILTERS_ATTR}]`),
  )) {
    const mount = runtimeRoot('depictio-report-mount depictio-report-filters');
    host.appendChild(mount);
    panels.push({
      host,
      mount,
      tabId: host.getAttribute(REPORT_FILTERS_ATTR) || manifest.dashboard.id,
    });
  }
  if (tiles.length === 0 && panels.length === 0) return;

  // React's own root draws nothing in place: every tile is a portal. Mantine's
  // portals (dropdowns, tooltips, the funnel modal) get a root of their own,
  // so they carry the runtime's tokens wherever they float.
  const reactRoot = runtimeRoot('depictio-report-host');
  reactRoot.hidden = true;
  const portalRoot = runtimeRoot('depictio-report-portal');
  document.body.append(reactRoot, portalRoot);

  const config = readConfig();
  const theme = mergeThemeOverrides(
    buildDepictioTheme({ brand: config.brand ?? null }),
    createTheme({
      components: { Portal: Portal.extend({ defaultProps: { target: portalRoot } }) },
    }),
  );

  ReactDOM.createRoot(reactRoot).render(
    <React.StrictMode>
      <MantineProvider
        theme={theme}
        forceColorScheme="light"
        cssVariablesSelector={`.${ROOT_CLASS}`}
        getRootElement={() => portalRoot}
      >
        <BrandingContext.Provider value={config.brand ?? null}>
          <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
            <StaticBadgeProvider tiers={manifest.tiers as StaticTierMap}>
              <ReportRuntime manifest={manifest} tiles={tiles} panels={panels} />
            </StaticBadgeProvider>
          </DatesProvider>
        </BrandingContext.Provider>
      </MantineProvider>
    </React.StrictMode>,
  );
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}

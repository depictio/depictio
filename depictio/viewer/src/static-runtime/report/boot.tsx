/**
 * The report host of the static runtime, hosted by a Quarto report.
 *
 * Booted by the static runtime's report entry (`combined/main.tsx`), in both
 * outputs of a report: the report alone, and the combined file, where it
 * shares one filter state with the dashboard view.
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
 * nothing here styles the page. The runtime's CSS is scoped onto its own roots
 * in the page (`combined/scopeStyles.ts`); Mantine's variables are written for
 * those roots only (`cssVariablesSelector`), and its portals land in a root of
 * their own at the end of <body>. Inter is already in the report (the Quarto
 * theme embeds it); the runtime adds no font face of its own to the page.
 *
 * Zero network, as the bundle: every api.ts call is shimmed.
 */
import React from 'react';
import { createPortal } from 'react-dom';
import ReactDOM from 'react-dom/client';
import { MantineProvider, Portal, mergeThemeOverrides, createTheme } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';

import {
  BrandingContext,
  StaticBadgeProvider,
  buildDepictioTheme,
  setChromeStyle,
  type StaticTierMap,
} from 'depictio-react-core';
import type { BundleManifest } from 'depictio-static-core';
import {
  REPORT_FILTERS_ATTR,
  REPORT_MANIFEST_ID,
  REPORT_TILE_ATTR,
  groupMountVerdict,
  parseTileRefs,
  restoreReportBasemaps,
} from 'depictio-static-core';

import paper from '../../chrome/variants/glass/glass';
import { installInlineMultiqcLogos } from '../../chrome/multiqcLogo';
import { installOfflineGenomeAssets } from '../genomeAssets';
import { loadBundleFromDocument, setActiveTab } from '../bundle';
import PinnedVersionBanner from '../PinnedVersionBanner';
import ReportRuntime, { type ReportPanel, type ReportTile } from './ReportRuntime';
import { readReportConfig, reportScheme, type Scheme } from './page';
import type { FilterChannel } from 'depictio-static-core';

/** The class every root of the runtime carries: what its CSS is scoped to. */
const ROOT_CLASS = 'depictio-report-root';

const roots: HTMLElement[] = [];

/** A root of the runtime: the class its scoped CSS keys on, Paper, in the
 *  report's scheme. */
function runtimeRoot(extraClass: string): HTMLDivElement {
  const el = document.createElement('div');
  el.className = `${ROOT_CLASS} ${extraClass}`;
  el.dataset.chrome = paper.id;
  el.setAttribute('data-mantine-color-scheme', reportScheme());
  roots.push(el);
  return el;
}

/** Mantine in the report's scheme, following it when the reader toggles. */
const SchemeProvider: React.FC<
  Omit<React.ComponentProps<typeof MantineProvider>, 'forceColorScheme'>
> = (props) => {
  const [scheme, setScheme] = React.useState<Scheme>(reportScheme);
  React.useEffect(() => {
    const sync = () => {
      const next = reportScheme();
      for (const el of roots) el.setAttribute('data-mantine-color-scheme', next);
      setScheme(next);
    };
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    sync();
    return () => observer.disconnect();
  }, []);
  return <MantineProvider {...props} forceColorScheme={scheme} />;
};

export interface BootReportOptions {
  /** One filter state shared with another view of the same file. */
  channel?: FilterChannel | null;
}

/** What the report host mounted: nothing when the page holds no manifest. */
export interface BootedReport {
  manifest: BundleManifest;
  tiles: ReportTile[];
}

/** Mount the report's tiles and filter panels; null when there is nothing to do. */
export function bootReport(options: BootReportOptions = {}): BootedReport | null {
  if (!document.getElementById(REPORT_MANIFEST_ID)) return null;
  let manifest;
  try {
    manifest = loadBundleFromDocument(REPORT_MANIFEST_ID);
  } catch (err) {
    // A manifest the runtime cannot read leaves every fallback in place.
    console.warn('[depictio report] manifest unreadable; the report keeps its own output', err);
    return null;
  }
  // A frozen map is frozen on a blank basemap for the offline bundle; in a
  // report, read online beside the export's own map, it keeps the dashboard's.
  restoreReportBasemaps(manifest);
  setActiveTab(manifest.dashboard.id);
  // The renderers style their figures through the active chrome (glassPlotly).
  setChromeStyle(paper);
  // file:// cannot reach `/dashboard/logos/...`: MultiQC tab icons use the
  // inlined copies instead.
  installInlineMultiqcLogos();
  // GenomeSpy tiles: the embedded font only (any other weight is fetched from
  // GitHub), and the gene tables the producer shipped (never `./assets/genomes`).
  installOfflineGenomeAssets();

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
  if (tiles.length === 0 && panels.length === 0) return { manifest, tiles };

  // React's own root draws nothing in place: every tile is a portal. Mantine's
  // portals (dropdowns, tooltips, the funnel modal) get a root of their own,
  // so they carry the runtime's tokens wherever they float.
  const reactRoot = runtimeRoot('depictio-report-host');
  reactRoot.hidden = true;
  const portalRoot = runtimeRoot('depictio-report-portal');
  document.body.append(reactRoot, portalRoot);

  // A pinned export says so above the report's own text (which names the
  // version too), with the collections it could not pin.
  let bannerHost: HTMLDivElement | null = null;
  if (manifest.pinned_version) {
    bannerHost = runtimeRoot('depictio-report-version');
    const flow = document.querySelector('main') ?? document.body;
    flow.prepend(bannerHost);
  }

  const config = readReportConfig();
  const theme = mergeThemeOverrides(
    buildDepictioTheme({ brand: config.brand ?? null }),
    createTheme({
      components: { Portal: Portal.extend({ defaultProps: { target: portalRoot } }) },
    }),
  );

  ReactDOM.createRoot(reactRoot).render(
    <React.StrictMode>
      <SchemeProvider
        theme={theme}
        cssVariablesSelector={`.${ROOT_CLASS}`}
        getRootElement={() => portalRoot}
      >
        <BrandingContext.Provider value={config.brand ?? null}>
          <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
            <StaticBadgeProvider
              tiers={manifest.tiers as StaticTierMap}
              exportedState={(manifest.initial_filters ?? []).length > 0}
            >
              {bannerHost &&
                manifest.pinned_version &&
                createPortal(
                  <PinnedVersionBanner
                    pinned={manifest.pinned_version}
                    project={manifest.project}
                    sticky={false}
                  />,
                  bannerHost,
                )}
              <ReportRuntime
                manifest={manifest}
                tiles={tiles}
                panels={panels}
                channel={options.channel ?? null}
              />
            </StaticBadgeProvider>
          </DatesProvider>
        </BrandingContext.Provider>
      </SchemeProvider>
    </React.StrictMode>,
  );
  return { manifest, tiles };
}

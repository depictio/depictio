/**
 * Google Analytics 4 bootstrap.
 *
 * `DEPICTIO_GOOGLE_ANALYTICS_ENABLED` / `_TRACKING_ID` have been documented in the
 * Helm chart — including real measurement IDs in the EMBL demo values files — for
 * some time, but nothing ever consumed them: no `gtag` snippet existed anywhere in
 * the tree, so operators who enabled it got silence. This is the missing consumer.
 *
 * It has to load the ID at runtime rather than at build time. The viewer ships as
 * a static nginx-served Vite bundle, so a build-time `VITE_` variable would bake
 * one operator's measurement ID into the shared image — which is why the chart's
 * `frontend.env` GA keys could never have worked. The backend is the source of
 * truth and serves the value from `/utils/public-config`.
 *
 * Opt-in per deployment: nothing loads and no Google script is fetched unless an
 * operator has explicitly configured a measurement ID.
 */

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

let initialised = false;

/**
 * Inject the GA4 tag for `trackingId`.
 *
 * Idempotent: React StrictMode double-invokes effects in development, and a second
 * injection would double-count every page view.
 */
export function initGoogleAnalytics(trackingId: string): void {
  if (initialised) return;
  if (!trackingId || !/^G-[A-Z0-9]+$/i.test(trackingId)) {
    // Guard against the chart's `G-XXXXXXXXXX` placeholder reaching the browser
    // and against anything that is not a measurement ID at all.
    return;
  }
  initialised = true;

  window.dataLayer = window.dataLayer || [];
  // GA's documented shim: `arguments`, not a rest parameter, because gtag.js
  // inspects `arguments` directly.
  window.gtag = function gtag() {
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer!.push(arguments);
  };

  window.gtag('js', new Date());
  window.gtag('config', trackingId, {
    // Depictio dashboards are a single-page app; sending page_view on every
    // history change is the host app's job, not gtag's guesswork.
    send_page_view: true,
    // No advertising features — this is product analytics for a research tool.
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    anonymize_ip: true,
  });

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(trackingId)}`;
  document.head.appendChild(script);
}

import { useEffect, useState } from 'react';

import { dashboardLogoIdFromUrl, signDashboardLogoUrls } from './api';

/**
 * A dashboard-logo URL made loadable by a bare `<img>` tag.
 *
 * `/dashboards/logo/{id}` no longer serves private dashboards to callers with
 * no credentials, and `<img>` cannot send any. The signed URL is minted by
 * `POST /dashboards/logo/sign` for the ids whose project the caller may read;
 * until it arrives (or if it fails, e.g. offline or for a public project that
 * serves the bare URL anyway) the stored URL is returned unchanged.
 */
export function useSignedDashboardLogoUrl(url: string | null | undefined): string | null {
  const [signed, setSigned] = useState<string | null>(url ?? null);
  useEffect(() => {
    if (!url) {
      setSigned(null);
      return;
    }
    setSigned(url);
    const dashboardId = dashboardLogoIdFromUrl(url);
    if (!dashboardId) return;
    let cancelled = false;
    signDashboardLogoUrls([dashboardId])
      .then((urls) => {
        if (!cancelled && urls[dashboardId]) setSigned(urls[dashboardId]);
      })
      .catch(() => {
        /* keep the stored URL: public projects still serve it */
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return signed;
}

import React from 'react';

/**
 * The deployment's opt-in feedback link, served by `/utils/public-config`.
 *
 * A dashboard shown to an audience you want to hear from needs the ask to sit
 * where the reader is looking. Feedback that arrives through some other channel
 * arrives without context: "that plot is wrong" with nothing saying which
 * dashboard, which tab, or which version — which is most of the work of acting
 * on it.
 *
 * The config lands after first paint (the `/utils/public-config` fetch is
 * fire-and-forget), so it flows through a tiny external store rather than React
 * state that may not exist yet — the same pattern branding uses. There is no
 * localStorage cache here on purpose: an un-rendered button for one frame costs
 * nothing, and a stale cached link outliving the deployment that set it does.
 */
export interface FeedbackConfig {
  enabled: boolean;
  /** Template; `{dashboard}`, `{dashboard_id}`, `{tab}` and `{url}` are substituted. */
  url: string | null;
  label: string;
}

let currentFeedback: FeedbackConfig | null = null;
const subscribers = new Set<() => void>();

export function getFeedback(): FeedbackConfig | null {
  return currentFeedback;
}

export function setFeedback(config: FeedbackConfig | null): void {
  const normalized = config?.enabled && config.url ? config : null;
  if (JSON.stringify(normalized) === JSON.stringify(currentFeedback)) return;
  currentFeedback = normalized;
  subscribers.forEach((fn) => fn());
}

export function subscribeFeedback(callback: () => void): () => void {
  subscribers.add(callback);
  return () => {
    subscribers.delete(callback);
  };
}

export interface FeedbackContext {
  /** The dashboard's own title — what a reader would name it in an issue. */
  dashboard?: string | null;
  dashboardId?: string | null;
  /** The tab that is on screen, which is usually what the remark is about. */
  tab?: string | null;
}

/**
 * Fill the deployment's URL template with what the reader is looking at.
 *
 * Every value is URL-encoded, so a template can drop `{dashboard}` straight
 * into a query string (a dashboard titled "CUT&RUN Chromatin Profiling" would
 * otherwise truncate the parameter). `{url}` is the current page, the one value
 * that still identifies what was on screen when the rest are blank.
 */
export function resolveFeedbackUrl(template: string, context: FeedbackContext): string {
  const values: Record<string, string> = {
    dashboard: context.dashboard ?? '',
    dashboard_id: context.dashboardId ?? '',
    tab: context.tab ?? '',
    url: typeof window === 'undefined' ? '' : window.location.href,
  };
  return template.replace(/\{(dashboard_id|dashboard|tab|url)\}/g, (_match, key: string) =>
    encodeURIComponent(values[key] ?? ''),
  );
}

/** The resolved link, or null when the deployment configured none. */
export function useFeedbackLink(context: FeedbackContext): { href: string; label: string } | null {
  const config = React.useSyncExternalStore(subscribeFeedback, getFeedback);
  const { dashboard, dashboardId, tab } = context;
  return React.useMemo(() => {
    if (!config?.url) return null;
    return {
      href: resolveFeedbackUrl(config.url, { dashboard, dashboardId, tab }),
      label: config.label || 'Feedback',
    };
  }, [config, dashboard, dashboardId, tab]);
}

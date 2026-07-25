/**
 * Shared visual tokens for the monitoring surfaces.
 *
 * Extracted verbatim from AdminMonitoringPanel so the project-scoped panels and
 * the agents pane render identically to the admin view rather than drifting
 * into their own palette. Colours are Mantine theme names, never literals.
 */

export const REFRESH_MS = 8000;

export const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  failure: 'red',
  failed: 'red',
  started: 'yellow',
  running: 'yellow',
  retry: 'orange',
  revoked: 'gray',
  pending: 'gray',
  partial: 'orange',
};

export const KIND_COLORS: Record<string, string> = {
  figure: 'blue',
  screenshot: 'grape',
  multiqc: 'teal',
  advanced_viz: 'indigo',
  deltatable: 'cyan',
  other: 'gray',
};

export const LOG_LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'gray',
  INFO: 'blue',
  WARNING: 'yellow',
  ERROR: 'red',
  CRITICAL: 'red',
};

/** Wrap long lines and reserve a right gutter so the CodeHighlight copy button
 *  never overlaps the code text. */
export const CODE_STYLES = {
  code: { whiteSpace: 'pre-wrap', wordBreak: 'break-word', paddingRight: 44 },
} as const;

/** Ultra-compact accordion: strip every border/divider and shrink control +
 *  label padding to the minimum legible so rows sit directly on top of each
 *  other. Shared by the Tasks / Ingestion / Logs panes. */
export const ACCORDION_STYLES = {
  root: { border: 'none' },
  item: { border: 'none', background: 'transparent' },
  control: { paddingTop: 0, paddingBottom: 0 },
  label: { paddingTop: 3, paddingBottom: 3 },
  content: { padding: '2px 8px 6px' },
} as const;

/** Viewport-relative height so the row list fills the available space under the
 *  pane header instead of a short fixed box. */
export const PANE_SCROLL_H = 'calc(100vh - 300px)';

export function statusColor(status?: string): string {
  return STATUS_COLORS[(status || '').toLowerCase()] || 'gray';
}

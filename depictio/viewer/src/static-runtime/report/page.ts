/**
 * What the report host reads from the Quarto page it is a guest in: the
 * report's config (written by the producer beside the manifest) and the
 * report's colour scheme. Shared by the tiles' host (`boot.tsx`) and the
 * combined file's chrome (`combined/host.ts`).
 */
import type { BrandTheme } from 'depictio-react-core';
import { REPORT_CONFIG_ID, type CombinedView } from 'depictio-static-core';

export type Scheme = 'light' | 'dark';

/** The `combined` section: the "Report | Dashboard" switch is on. */
export interface CombinedConfig {
  /** The view a file opens on when its link names none (chosen at export). */
  default_view?: CombinedView;
}

/** `#depictio-report-config` (`report_runtime.runtime_parts`). */
export interface ReportConfig {
  /** The report's brand: its primary colour and font, so a tile's accent is
   *  the document's. */
  brand?: BrandTheme | null;
  /** Present in the combined output only; a report-only file has none. */
  combined?: CombinedConfig | null;
}

export function readReportConfig(doc: Document = document): ReportConfig {
  try {
    const raw = doc.getElementById(REPORT_CONFIG_ID)?.textContent;
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return parsed && typeof parsed === 'object' ? (parsed as ReportConfig) : {};
  } catch {
    return {};
  }
}

/** The report's own scheme: Quarto marks its dark page `body.quarto-dark`
 *  (the reader's preference, or its toggle). */
export function reportScheme(doc: Document = document): Scheme {
  return doc.body?.classList.contains('quarto-dark') ? 'dark' : 'light';
}

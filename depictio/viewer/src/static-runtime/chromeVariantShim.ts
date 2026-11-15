/**
 * Shim for viewer/src/chrome/variants/index.ts in static bundles.
 *
 * A bundle draws the Classic chrome (`base`), whatever the exporting instance
 * or the reader's browser prefers. The read-only gating of a bundle (no Edit,
 * no "Back to Dashboards", no server, auth or profile chrome, the export
 * provenance in the rail) is wired into the Classic shell's Header and
 * Sidebar; the Glass shell draws its own rail, dock and profile tile, which
 * are not gated yet, and would offer links to routes a file does not have.
 *
 * Everything else is the real module (`export *`); only the two hooks that
 * pick a style are replaced, and the style is set once at load, after the
 * real module's own resolution ran.
 */
import { BASE_CHROME_STYLE, setChromeStyle } from 'depictio-react-core';

import DefaultShell from '../chrome/shell/DefaultShell';
import type { DashboardShell } from '../chrome/shell/types';

export * from '../chrome/variants/index';

setChromeStyle(BASE_CHROME_STYLE);

/** No profile pick and no instance default inside a bundle: nothing to follow. */
export function useChromeVariant(): void {}

/** The Classic page layout, always. */
export function useDashboardShell(): DashboardShell {
  return DefaultShell;
}

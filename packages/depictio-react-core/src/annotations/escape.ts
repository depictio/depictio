/**
 * Which Escape presses leave annotate mode. The annotate handlers listen on
 * `window`, so without this they would also fire for an Esc meant for some
 * other open overlay (a modal, a menu, a select dropdown). No React; the DOM
 * is only touched through `closest`, so it is unit tested with stubs.
 */

/** Marks the annotate toolbar and its label popover. */
export const ANNOTATE_UI_ATTR = 'data-depictio-annotate-ui';

/** Open Mantine overlays whose own Esc handling must win. */
export const FOREIGN_OVERLAY_SELECTOR = [
  '[role="dialog"]',
  '[role="menu"]',
  '[role="listbox"]',
  '.mantine-Popover-dropdown',
  '.mantine-Menu-dropdown',
  '.mantine-Combobox-dropdown',
  '.mantine-Modal-content',
  '.mantine-Drawer-content',
].join(', ');

interface ClosestLike {
  closest?: (selector: string) => ClosestLike | null;
  contains?: (other: unknown) => boolean;
}

export interface EscapeLike {
  key: string;
  defaultPrevented: boolean;
  target: unknown;
}

/**
 * Whether this keydown should cancel the pending label / leave annotate mode:
 * an Escape nobody handled yet, pressed in the annotate UI, outside any
 * overlay, or inside the overlay that hosts the annotated component (`host`,
 * e.g. a fullscreen modal holding the plot) -- never in some other overlay.
 */
export function isAnnotateEscape(e: EscapeLike, host?: unknown): boolean {
  if (e.key !== 'Escape' || e.defaultPrevented) return false;
  const target = e.target as ClosestLike | null;
  if (typeof target?.closest !== 'function') return true;
  if (target.closest(`[${ANNOTATE_UI_ATTR}]`)) return true;
  const overlay = target.closest(FOREIGN_OVERLAY_SELECTOR);
  if (!overlay) return true;
  return host != null && typeof overlay.contains === 'function' && overlay.contains(host);
}

/**
 * Another tile of the dashboard, found by its index: its title, to name it,
 * and a ring around it, to point at it. A genome view and the genome browser
 * that follows its region use both to show which one drives the other.
 *
 * Both read the chrome's marks (`data-component-index`, `data-component-title`
 * on `ComponentChrome`), so they work wherever the tile is drawn and need no
 * registry of the dashboard's components.
 */

const RING_CLASS = 'depictio-link-ring';

function tileElement(index: string): HTMLElement | null {
  if (typeof document === 'undefined' || !index) return null;
  const el = document.querySelector<HTMLElement>(`[data-component-index="${CSS.escape(index)}"]`);
  if (!el) return null;
  return el.closest<HTMLElement>('.react-grid-item') ?? el;
}

/** The title tile `index` shows, or null while it is not on the page. */
export function tileTitle(index: string | null | undefined): string | null {
  if (!index || typeof document === 'undefined') return null;
  const el = document.querySelector<HTMLElement>(`[data-component-index="${CSS.escape(index)}"]`);
  const title = el?.getAttribute('data-component-title')?.trim();
  return title || null;
}

/** Ring tile `index` (or drop the ring). A no-op while it is not on the page. */
export function ringTile(index: string | null | undefined, on: boolean): void {
  if (!index) return;
  tileElement(index)?.classList.toggle(RING_CLASS, on);
}

/**
 * The colour of a genome browser's link to a genome view: the dashed band its
 * window draws on the view, and the chips both tiles show for each other.
 * A Mantine colour name, so it follows the theme's shades.
 */
export const LINK_COLOR = 'violet';

/** Scroll tile `index` into view and ring it for a moment. */
export function flashTile(index: string | null | undefined, ms = 1600): void {
  if (!index) return;
  const el = tileElement(index);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  el.classList.add(RING_CLASS);
  window.setTimeout(() => el.classList.remove(RING_CLASS), ms);
}

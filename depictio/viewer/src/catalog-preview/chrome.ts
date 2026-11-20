/**
 * The catalog preview draws in the app's chrome style, Paper by default.
 *
 * It used to draw nothing but Mantine defaults, which is the app's Classic
 * look: a violet catalogue beside a Paper app, and, inside the editor's
 * catalog picker, a Classic tile in a Paper page. The picker embeds this
 * bundle in an iframe of the same origin, so reading the app's own keys
 * (`resolveChromeId`) makes the tile follow the reader's pick. A standalone
 * file (`depictio catalog gallery`, the docs) has no pick and gets Paper.
 *
 * `#chrome=base` (or `?chrome=base`) forces Classic, for comparison.
 */
import { BASE_CHROME_STYLE, setChromeStyle } from 'depictio-react-core';
import type { ChromeStyle } from 'depictio-react-core';

import glass from '../chrome/variants/glass/glass';
import { resolveChromeId } from '../chrome/variants/resolveId';
import '../chrome/variants/glass/layout.css';
import '../chrome/variants/glass/pages/pages.css';
import './catalog-paper.css';

const STYLES: ChromeStyle[] = [glass, BASE_CHROME_STYLE];
const BY_ID = new Map(STYLES.map((s) => [s.id, s]));
const KNOWN: ReadonlySet<string> = new Set(BY_ID.keys());

function hashChromeId(): string | null {
  const m = window.location.hash.match(/[#&]chrome=([^&]*)/);
  const id = m ? decodeURIComponent(m[1]).toLowerCase() : null;
  return id && KNOWN.has(id) ? id : null;
}

/** Applied before the first render, so no frame paints in another style. */
export function applyCatalogChrome(): ChromeStyle {
  const id = hashChromeId() ?? resolveChromeId(KNOWN);
  const style = (id && BY_ID.get(id)) || glass;
  setChromeStyle(style);
  // The Paper page rules that style portalled surfaces (popovers, menus) and
  // tags key on this mark, as on the app's own pages.
  if (style.id === glass.id) document.documentElement.setAttribute('data-gp-page', 'catalog');
  else document.documentElement.removeAttribute('data-gp-page');
  return style;
}

export const PAPER_ID = glass.id;

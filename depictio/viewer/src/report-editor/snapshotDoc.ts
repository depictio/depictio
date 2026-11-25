/**
 * The document a tile snapshot is drawn in: the report's own stylesheets and
 * classes around the tile's markup, with a <base> so its relative URLs reach
 * the preview files. Pure string work; the frame that shows it has no scripts.
 */
import type { PreviewStyles } from './previewProtocol';

/** The width the snapshot is laid out at before it is scaled down. */
export const VIRTUAL_WIDTH = 720;

/** The width a component is laid out at before being scaled into its box: a
 *  KPI card is narrow in the report, a table or a long text wide. Laid out at
 *  the table's width, a card would be a speck in the corner of its thumbnail. */
export function virtualWidthFor(componentType: string | null | undefined): number {
  if (componentType === 'card') return 260;
  if (componentType === 'text') return 520;
  return VIRTUAL_WIDTH;
}

const attr = (value: string): string =>
  value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

export function buildSnapshotDoc(
  html: string,
  styles: PreviewStyles | null,
  baseUrl: string | null,
  scrollable: boolean,
  virtualWidth: number = VIRTUAL_WIDTH,
): string {
  const base = baseUrl ? `<base href="${attr(new URL(baseUrl, window.location.href).href)}">` : '';
  const links = (styles?.links ?? [])
    .map((href) => `<link rel="stylesheet" href="${attr(href)}">`)
    .join('');
  // A literal end tag inside the css would close its <style>.
  const css = (styles?.css ?? '').replace(/<\/style/gi, '<\\/style');
  const scheme = styles?.colorScheme ? `color-scheme:${styles.colorScheme.replace(/[^a-z ]/gi, '')};` : '';
  // Transparent around the component: the report's page background is not
  // part of it. A thumbnail has no padding either, only the component shows.
  const frameCss = `html,body{margin:0;min-width:0;background:transparent!important;${scrollable ? '' : 'overflow:hidden;'}}body{padding:${scrollable ? 8 : 0}px;box-sizing:border-box;width:${virtualWidth}px;pointer-events:${scrollable ? 'auto' : 'none'}}`;
  return (
    `<!doctype html><html class="${attr(styles?.htmlClass ?? '')}" style="${scheme}">` +
    `<head><meta charset="utf-8">${base}${links}<style>${css}</style><style>${frameCss}</style></head>` +
    `<body class="${attr(styles?.bodyClass ?? '')}">${html}</body></html>`
  );
}

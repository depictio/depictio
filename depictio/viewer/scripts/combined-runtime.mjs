/**
 * The combined file's runtime parts, composed in JS for the demo site, the
 * budget floor and the offline specs: the same order and escaping as the
 * producer (depictio/serverless/combined.py::compose_combined) for a report
 * that carries no Plotly copy of its own — the config and the manifest, the
 * stylesheet as inert text, the add-ons, then the runtime's script, at the end
 * of the page.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const jsonScript = (id, payload) =>
  `<script type="application/json" id="${id}">${JSON.stringify(payload)
    .replace(/<\//g, '<\\/')
    .replace(/<!--/g, '<\\u0021--')}</script>`;

const inert = (text) => text.replace(/<\/script/g, '<\\/script').replace(/<!--/g, '<\\!--');

/** `dist-static/combined-runtime.{js,css}`, or null when not built. */
export function readCombinedRuntime(distStatic) {
  const js = join(distStatic, 'combined-runtime.js');
  const css = join(distStatic, 'combined-runtime.css');
  if (!existsSync(js) || !existsSync(css)) return null;
  return { js: readFileSync(js, 'utf-8'), css: readFileSync(css, 'utf-8') };
}

export function composeCombined({
  js,
  css,
  manifest,
  config = {},
  addons = '',
  defaultView = 'report',
}) {
  return [
    jsonScript('depictio-report-config', { ...config, combined: { default_view: defaultView } }),
    manifest == null ? '' : jsonScript('depictio-report-manifest', manifest),
    `<script type="text/plain" data-depictio-runtime="css">${inert(css)}</script>`,
    addons,
    `<script data-depictio-runtime="js">${inert(js)}</script>`,
  ].join('');
}

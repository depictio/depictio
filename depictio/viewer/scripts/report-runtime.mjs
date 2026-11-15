/**
 * The report host's block, composed in JS for the demo site and the budget
 * floor: the same order and the same escaping as the producer
 * (depictio/notebook/report_runtime.py::compose_report_runtime) — the runtime's
 * stylesheet, the report's look, the manifest, any add-on, the runtime's script.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export const REPORT_TOKEN = '<!--DEPICTIO_REPORT_RUNTIME-->';

const jsonScript = (id, payload) =>
  `<script type="application/json" id="${id}">${JSON.stringify(payload)
    .replace(/<\//g, '<\\/')
    .replace(/<!--/g, '<\\u0021--')}</script>`;

/** `dist-static/report-runtime.{js,css}`, or null when not built. */
export function readReportRuntime(distStatic) {
  const js = join(distStatic, 'report-runtime.js');
  const css = join(distStatic, 'report-runtime.css');
  if (!existsSync(js) || !existsSync(css)) return null;
  return { js: readFileSync(js, 'utf-8'), css: readFileSync(css, 'utf-8') };
}

export function composeReportRuntime({ js, css, manifest, config = {}, addons = '' }) {
  const script = js.replace(/<\/script/g, '<\\/script').replace(/<!--/g, '<\\!--');
  return [
    `<style data-depictio-report-runtime="css">${css.replace(/<\/style/g, '<\\/style')}</style>`,
    jsonScript('depictio-report-config', config),
    manifest == null ? '' : jsonScript('depictio-report-manifest', manifest),
    addons,
    `<script data-depictio-report-runtime="js">${script}</script>`,
  ].join('');
}

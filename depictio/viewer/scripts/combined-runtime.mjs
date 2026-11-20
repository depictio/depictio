/**
 * The runtime a report embeds, composed in JS for the demo site and the budget
 * floor: the parts of the producer's composition
 * (depictio/notebook/report_runtime.py::runtime_parts, placed by
 * depictio/serverless/combined.py::compose_report) for a report that carries
 * no Plotly copy of its own — the config (with its `combined` section for the
 * combined output), the manifest, the stylesheet as inert text, the add-ons,
 * then the runtime's script, at the end of the page. Held to the producer's
 * bytes by depictio/tests/unit/serverless/test_runtime_compose_parity.py.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/** Where the demo report skeleton takes the runtime. */
export const REPORT_TOKEN = '<!--DEPICTIO_REPORT_RUNTIME-->';

// Python's json.dumps(separators=(",", ":")) writes non-ASCII as \uXXXX.
const asciiJson = (payload) =>
  JSON.stringify(payload).replace(
    /[\u0080-\uffff]/g,
    (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );

const jsonScript = (id, payload) =>
  `<script type="application/json" id="${id}">${asciiJson(payload)
    .replace(/<\//g, '<\\/')
    .replace(/<!--/g, '<\\u0021--')}</script>`;

const scriptText = (text) => text.replace(/<\/script/g, '<\\/script').replace(/<!--/g, '<\\!--');

/** `dist-static/combined-runtime.{js,css}`, or null when not built. */
export function readCombinedRuntime(distStatic) {
  const js = join(distStatic, 'combined-runtime.js');
  const css = join(distStatic, 'combined-runtime.css');
  if (!existsSync(js) || !existsSync(css)) return null;
  return { js: readFileSync(js, 'utf-8'), css: readFileSync(css, 'utf-8') };
}

/** `output`: 'report' (the report alone) or 'combined' (with the dashboard). */
export function composeRuntime({
  js,
  css,
  manifest,
  config = {},
  addons = '',
  output = 'report',
  defaultView = 'report',
}) {
  const { combined: _ignored, ...look } = config;
  const section = output === 'combined' ? { combined: { default_view: defaultView } } : {};
  return [
    jsonScript('depictio-report-config', { ...look, ...section }),
    jsonScript('depictio-report-manifest', manifest),
    `<script type="text/plain" data-depictio-runtime="css">${scriptText(css)}</script>`,
    addons,
    `<script data-depictio-runtime="js">${scriptText(js)}</script>`,
  ].join('');
}

// `node combined-runtime.mjs <args.json>`: the composition of the arguments,
// on stdout (the parity test's entry).
if (process.argv[1] && process.argv[1].endsWith('combined-runtime.mjs') && process.argv[2]) {
  process.stdout.write(composeRuntime(JSON.parse(readFileSync(process.argv[2], 'utf-8'))));
}

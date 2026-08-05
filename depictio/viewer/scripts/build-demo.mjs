#!/usr/bin/env node
/**
 * Build openable demo pages from the static-runtime bundle.
 *
 * Reads the demo registry (demo/manifests.json), injects each manifest into
 * the built template (dist-static/static.html) and writes a self-contained
 * site under dist-static/site/: one demo-<id>.html per registry entry plus an
 * index.html linking them. The site is what CI uploads as an artifact and what
 * the GH Pages workflow publishes — each serverless phase appends a registry
 * entry, earlier demos stay, so the evolution is browsable side by side.
 *
 * Injection matches the Python producers (depictio/catalog/payload.py::_inject):
 * replace every token occurrence, escape `</` in the JSON blob. The function
 * replacement form is required — a plain string would interpret `$` sequences.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const VIEWER_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TEMPLATE = join(VIEWER_DIR, 'dist-static', 'static.html');
const REGISTRY = join(VIEWER_DIR, 'demo', 'manifests.json');
const SITE_DIR = join(VIEWER_DIR, 'dist-static', 'site');
const TOKEN = '__BUNDLE_MANIFEST__';

if (!existsSync(TEMPLATE)) {
  console.error(
    'dist-static/static.html not found — run `pnpm run build:static` first ' +
      '(or `pnpm run demo:static`, which chains both).',
  );
  process.exit(1);
}

const template = readFileSync(TEMPLATE, 'utf-8');
const registry = JSON.parse(readFileSync(REGISTRY, 'utf-8'));
mkdirSync(SITE_DIR, { recursive: true });

const escapeHtml = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const entries = [];
for (const entry of registry) {
  const manifestPath = resolve(VIEWER_DIR, entry.manifest);
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));
  const blob = JSON.stringify(manifest).replace(/<\//g, '<\\/');
  const html = template.replaceAll(TOKEN, () => blob);
  const out = join(SITE_DIR, `demo-${entry.id}.html`);
  writeFileSync(out, html);
  entries.push({ ...entry, file: `demo-${entry.id}.html`, bytes: html.length });
  console.log(`demo-${entry.id}.html: ${(html.length / 1e6).toFixed(2)} MB — ${entry.title}`);
}

const sha = process.env.GITHUB_SHA?.slice(0, 8) ?? 'local';
const built = new Date().toISOString();
const rows = entries
  .map(
    (e) => `      <li>
        <a href="${e.file}"><strong>${escapeHtml(e.title)}</strong></a>
        <span class="size">${(e.bytes / 1e6).toFixed(1)} MB</span>
        <p>${escapeHtml(e.description)}</p>
      </li>`,
  )
  .join('\n');

writeFileSync(
  join(SITE_DIR, 'index.html'),
  `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Depictio — serverless demos</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }
    h1 { font-size: 1.5rem; } h1 small { font-weight: normal; opacity: 0.6; }
    ul { list-style: none; padding: 0; }
    li { margin: 1.25rem 0; padding: 1rem 1.25rem; border: 1px solid color-mix(in srgb, currentColor 20%, transparent); border-radius: 8px; }
    li p { margin: 0.4rem 0 0; opacity: 0.8; font-size: 0.92rem; }
    .size { opacity: 0.55; font-size: 0.85rem; margin-left: 0.5rem; }
    footer { margin-top: 2.5rem; opacity: 0.55; font-size: 0.85rem; }
    a { color: inherit; }
  </style>
</head>
<body>
  <h1>Depictio serverless — phase demos <small>one page per milestone</small></h1>
  <p>Each demo is a fully self-contained HTML file: the real Depictio viewer running
     without any backend or network. Open one, then try it from a saved local copy —
     it works from <code>file://</code> too. Design:
     <a href="https://github.com/depictio/depictio/blob/feat/serverless-deployment/docs/design/rfc-serverless-deployment.md">RFC</a> ·
     <a href="https://github.com/depictio/depictio/blob/feat/serverless-deployment/docs/design/serverless-engine-spike.md">engine spike</a>.</p>
  <ul>
${rows}
  </ul>
  <footer>Built ${built} from <code>${sha}</code>.</footer>
</body>
</html>
`,
);
console.log(`site: ${entries.length} demo(s) + index.html → dist-static/site/`);

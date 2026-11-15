/**
 * Append runtime add-ons to a built static template — the JS twin of
 * depictio/serverless/addons.py::apply_addons (same element, same place:
 * before the last `</body>`), for the demo site and the offline specs.
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ADDONS_DIR = join(
  resolve(dirname(fileURLToPath(import.meta.url)), '..'),
  'dist-static',
  'addons',
);

export function addonRegistry(dir = ADDONS_DIR) {
  return JSON.parse(readFileSync(join(dir, 'addons.json'), 'utf-8'));
}

/** The manifest `addons` entry for one built add-on. */
export function addonEntry(name, reason, dir = ADDONS_DIR) {
  const info = addonRegistry(dir)[name];
  if (!info) throw new Error(`add-on ${name} is not built (run pnpm run build:static)`);
  return { name, version: info.version, packages: [], bytes: info.bytes, reason };
}

export function applyAddons(template, names, dir = ADDONS_DIR) {
  if (!names.length) return template;
  const registry = addonRegistry(dir);
  const scripts = names
    .map((n) => {
      const info = registry[n];
      if (!info) throw new Error(`add-on ${n} is not built (run pnpm run build:static)`);
      const body = readFileSync(join(dir, info.file), 'utf-8');
      return `<script data-depictio-addon="${n}">${body}</script>`;
    })
    .join('');
  const at = template.lastIndexOf('</body>');
  return at < 0 ? template + scripts : template.slice(0, at) + scripts + template.slice(at);
}

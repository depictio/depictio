/**
 * Access to the embedded bundle manifest for the static runtime.
 *
 * `main.tsx` parses the `<script id="bundle-manifest">` JSON onto
 * `window.__DEPICTIO_BUNDLE__` before anything else runs; the api shims read
 * it through `bundle()`. Keying rules mirror the manifest contract: frozen
 * payloads are keyed by component index (`StoredMetadata.index`), and
 * interactive lookups are resolved dc_id+column -> component index via the
 * dashboard document.
 */
import { parseManifest, type BundleManifest } from 'depictio-static-core';

declare global {
  interface Window {
    __DEPICTIO_BUNDLE__?: BundleManifest;
  }
}

export function loadBundleFromDocument(): BundleManifest {
  const el = document.getElementById('bundle-manifest');
  const manifest = parseManifest(JSON.parse(el?.textContent || 'null'));
  window.__DEPICTIO_BUNDLE__ = manifest;
  return manifest;
}

export function bundle(): BundleManifest {
  const manifest = window.__DEPICTIO_BUNDLE__;
  if (!manifest) {
    throw new Error('static runtime: bundle manifest not loaded (main.tsx must run first)');
  }
  return manifest;
}

/** Frozen payload for a component index; throws a readable error on a miss. */
export function frozenPayload<T>(componentIndex: string, kind: string): T {
  const entry = bundle().frozen[componentIndex];
  if (!entry) {
    throw new Error(`static bundle: no frozen ${kind} payload for "${componentIndex}"`);
  }
  return entry.payload as T;
}

interface ComponentMeta {
  index?: string;
  component_type?: string;
  interactive_component_type?: string;
  dc_id?: string | null;
  column_name?: string;
  [key: string]: unknown;
}

function storedMetadata(): ComponentMeta[] {
  const doc = bundle().dashboard.doc as { stored_metadata?: ComponentMeta[] };
  return doc.stored_metadata ?? [];
}

/** Resolve an interactive component's index from the (dc_id, column) its
 *  renderer passes to fetchUniqueValues / fetchColumnRange / fetchSpecs. */
export function interactiveIndexFor(dcId: string, columnName?: string): string | undefined {
  return storedMetadata().find(
    (c) =>
      c.component_type === 'interactive' &&
      String(c.dc_id ?? '') === dcId &&
      (columnName === undefined || c.column_name === columnName),
  )?.index;
}

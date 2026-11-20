/**
 * The base runtime's side of the `jbrowse` add-on.
 *
 * The add-on (depictio-react-core `components/jbrowse/vendorModules.ts`,
 * built by `vite.static-jbrowse.config.ts`) is a classic script a producer
 * appends to a bundle holding a genome browser tile. It defines one global,
 * `__depictioJBrowseVendor`, a factory: React is an external of that build, so
 * the add-on cannot run before the runtime hands it the runtime's own React.
 * The first forwarder to be evaluated calls the factory here, once.
 *
 * Without the add-on every forwarded module is a stand-in whose members are
 * inert placeholders: callable, extendable (`class X extends Plugin`) and
 * returning undefined, so the modules that build JBrowse plugins at import
 * time still evaluate, and the static JBrowseRenderer (jbrowseStub.tsx) shows
 * the session table instead of mounting the browser.
 */
import * as React from 'react';
import * as ReactDOM from 'react-dom';
import * as ReactDOMClient from 'react-dom/client';
import * as JsxRuntime from 'react/jsx-runtime';

type Namespace = Record<string, unknown>;
type Factory = (
  react: unknown,
  reactDom: unknown,
  reactDomClient: unknown,
  jsxRuntime: unknown,
) => { modules: Record<string, Namespace> };

export const VENDOR_GLOBAL = '__depictioJBrowseVendor';

let modules: Record<string, Namespace> | null | undefined;
let loadError: string | null = null;

function load(): Record<string, Namespace> | null {
  if (modules !== undefined) return modules;
  const factory = (globalThis as unknown as Record<string, unknown>)[VENDOR_GLOBAL] as
    | Factory
    | undefined;
  modules = null;
  if (typeof factory === 'function') {
    try {
      modules = factory(React, ReactDOM, ReactDOMClient, JsxRuntime).modules;
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
      console.error('static bundle: the JBrowse add-on failed to start', err);
    }
  }
  return modules;
}

/** True when the add-on is embedded and started. */
export function jbrowseVendorLoaded(): boolean {
  return load() !== null;
}

/** Why the add-on is not usable, for the tile's fallback note. */
export function jbrowseVendorProblem(): string {
  if (jbrowseVendorLoaded()) return '';
  return loadError
    ? `the genome browser add-on failed to start (${loadError})`
    : 'this bundle was built without the genome browser add-on';
}

// eslint-disable-next-line @typescript-eslint/no-empty-function
function placeholder(): undefined {
  return undefined;
}

const INERT: Namespace = new Proxy(
  {},
  {
    get: (_t, key) => (key === '__esModule' ? true : placeholder),
  },
);

/** Views a bundle never opens (see vendorModules.ts). */
const NOT_BUNDLED: Record<string, Namespace> = {
  '@jbrowse/react-circular-genome-view2': {},
  '@jbrowse/react-app2': {},
};

function notBundled(spec: string): Namespace {
  const fail = () => {
    throw new Error(`${spec} is not part of a static bundle`);
  };
  return new Proxy({}, { get: (_t, key) => (key === '__esModule' ? true : fail) });
}

/** The namespace of one forwarded specifier. */
export function vendorModule(spec: string): Namespace {
  if (spec in NOT_BUNDLED) return notBundled(spec);
  const mods = load();
  if (!mods) return INERT;
  const ns = mods[spec];
  if (!ns) {
    console.error(`static bundle: the JBrowse add-on does not provide ${spec}`);
    return INERT;
  }
  return ns;
}

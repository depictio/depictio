/**
 * What the offline api shim reads: the fixture currently loaded in the Studio,
 * plus the metadata of every component on screen.
 *
 * Deliberately dependency-free (types only). The shim is pulled in by
 * depictio-react-core's own modules, so anything it imports at runtime would
 * risk an import cycle through the component tree; a plain module-level
 * registry is the same trick `window.__CATALOG_PREVIEW__` plays for the
 * catalog-preview bundle, minus the global.
 *
 * Two keying conventions, mirroring depictio's own endpoints: the ones that
 * carry a component id (`renderFigure`, `renderTable`) look the component up
 * here, and the ones that carry a `dc_id` answer from the single active
 * fixture — the Studio only ever has one data collection.
 */
import type { ParsedFixture } from '../types';
import type { StudioFrame } from './frame';
import { buildFrame } from './frame';

/** The subset of depictio's `StoredMetadata` the shim reads back. */
export interface ComponentMetadata {
  index: string;
  component_type?: string;
  [key: string]: unknown;
}

let fixture: ParsedFixture | null = null;
const components = new Map<string, ComponentMetadata>();

export function setActiveFixture(next: ParsedFixture | null): void {
  fixture = next;
}

export function getActiveFixture(): ParsedFixture | null {
  return fixture;
}

/** The typed frame for the active fixture, or null when none is loaded.
 *  `buildFrame` memoises per fixture object, so this is cheap to call. */
export function getActiveFrame(): StudioFrame | null {
  return fixture ? buildFrame(fixture) : null;
}

/** Register (or replace) one component's metadata under its index. */
export function registerComponent(metadata: ComponentMetadata): void {
  if (metadata?.index) components.set(String(metadata.index), metadata);
}

export function unregisterComponent(index: string): void {
  components.delete(index);
}

export function getComponent(index: string): ComponentMetadata | undefined {
  return components.get(index);
}

/** Every registered card — what `bulkComputeCards` iterates when the caller
 *  doesn't name specific components. */
export function cardComponents(): ComponentMetadata[] {
  return [...components.values()].filter((m) => m.component_type === 'card');
}

/** Everything on screen. Served as the synthetic dashboard's `stored_metadata`,
 *  which is how `InteractiveBuilder` finds sibling filters to suggest a group
 *  from. */
export function allComponents(): ComponentMetadata[] {
  return [...components.values()];
}

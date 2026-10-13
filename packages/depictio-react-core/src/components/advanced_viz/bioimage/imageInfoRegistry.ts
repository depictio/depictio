import { useSyncExternalStore } from 'react';

import type { BioimageInfo } from './viewer';

/** What the viewer read from the image it has open for one component: the
 *  store's name and the metadata the load returned. The component's Info tab
 *  reads it, so the tab shows what the tile is drawing, not a second read. */
export interface PublishedImageInfo {
  store: string;
  info: BioimageInfo;
}

// Module-level, not React state: the renderer that loads an image and the
// Info tab that shows it sit in different parts of the tree.
const published = new Map<string, PublishedImageInfo>();
const listeners = new Set<() => void>();

const notify = () => listeners.forEach((listener) => listener());

export function publishImageInfo(componentKey: string, entry: PublishedImageInfo): void {
  published.set(componentKey, entry);
  notify();
}

export function clearImageInfo(componentKey: string): void {
  if (published.delete(componentKey)) notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The image a component's tile last loaded, or null before it has loaded one. */
export function useImageInfo(componentKey: string | null): PublishedImageInfo | null {
  return useSyncExternalStore(
    subscribe,
    () => (componentKey === null ? null : (published.get(componentKey) ?? null)),
    () => null,
  );
}

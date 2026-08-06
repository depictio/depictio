import React, { createContext, useContext } from 'react';

/**
 * Lets the app hang an "inspect this component" action off every component's
 * chrome without this package learning about the app's store.
 *
 * `depictio-react-core` declares no direct dependencies — everything is a peer
 * — so it must not import zustand to reach `useUiStore`. A context keeps the
 * dependency pointing the right way: the viewer provides, the chrome consumes.
 *
 * A null context (the default) is also the feature flag: with the inspector
 * disabled the viewer never mounts a provider, `ComponentChrome` finds nothing,
 * and no inspect action is rendered anywhere.
 */
export interface InspectorControl {
  /** `StoredMetadata.index` currently shown, or null. */
  selectedId: string | null;
  /** Toggles: selecting the component already shown closes the inspector. */
  select: (componentId: string) => void;
}

export const InspectorContext = createContext<InspectorControl | null>(null);

/** `value={null}` is the disabled state — consumers see no control and render
 *  no inspect action, so the app can mount this unconditionally. */
export const InspectorProvider: React.FC<{
  value: InspectorControl | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <InspectorContext.Provider value={value}>{children}</InspectorContext.Provider>
);

export function useInspectorControl(): InspectorControl | null {
  return useContext(InspectorContext);
}

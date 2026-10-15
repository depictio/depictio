/**
 * Whether the tiles of the current tab carry a unit chip, and in which colour.
 *
 * A host (the viewer, the editor) provides it once for the tab, non-null only
 * when an `always_selected` filter sets the tab's scope (`scopeUnits`). A tile
 * that shows one unit passes that unit as `scopeLabel` to its frame; the frame
 * draws the chip only under a provider, so the same tile elsewhere (another
 * tab, the Guide, a screenshot of a tab without a scope) stays as it was.
 *
 * Kept free of renderer imports: the hosts mount it at boot.
 */
import React from 'react';

export interface ScopeChip {
  /** Badge colour (see `scopeChipColor`); undefined is the primary. */
  color?: string;
}

export const ScopeChipContext = React.createContext<ScopeChip | null>(null);

export const ScopeChipProvider: React.FC<{
  value: ScopeChip | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <ScopeChipContext.Provider value={value}>{children}</ScopeChipContext.Provider>
);

export function useScopeChip(): ScopeChip | null {
  return React.useContext(ScopeChipContext);
}

/**
 * Puts "Export / embed" on every tile of the page, when the server's export
 * API is on, and owns the one dialog those actions open.
 *
 * The chrome lives in depictio-react-core and knows nothing of this dialog or
 * of the server flag; it draws the action only while `ComponentExportContext`
 * holds a value (see `ExportContext.tsx`). Off, this renders its children
 * alone and no tile changes.
 */
import React, { useCallback, useMemo, useState } from 'react';
import { ComponentExportControlProvider } from 'depictio-react-core';
import type { ComponentExportControl, ComponentExportTarget } from 'depictio-react-core';

import ComponentExportModal from './ComponentExportModal';

export interface ComponentExportProviderProps {
  /** `embed_enabled` from `/auth/me/optional`. */
  enabled: boolean;
  /** `embed_framing_enabled` from `/auth/me/optional`. */
  framingEnabled: boolean;
  /** The dashboard's project is public (no token needed to export). */
  isPublic: boolean;
  children: React.ReactNode;
}

const ComponentExportProvider: React.FC<ComponentExportProviderProps> = ({
  enabled,
  framingEnabled,
  isPublic,
  children,
}) => {
  const [target, setTarget] = useState<ComponentExportTarget | null>(null);
  const open = useCallback((next: ComponentExportTarget) => setTarget(next), []);
  const control = useMemo<ComponentExportControl | null>(
    () => (enabled ? { open } : null),
    [enabled, open],
  );

  return (
    <ComponentExportControlProvider value={control}>
      {children}
      {enabled ? (
        <ComponentExportModal
          target={target}
          onClose={() => setTarget(null)}
          isPublic={isPublic}
          framingEnabled={framingEnabled}
        />
      ) : null}
    </ComponentExportControlProvider>
  );
};

export default ComponentExportProvider;

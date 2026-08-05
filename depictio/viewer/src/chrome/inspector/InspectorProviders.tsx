import React from 'react';
import { AdvancedVizInspectorProvider, InspectorProvider } from 'depictio-react-core';
import type { InspectorControl } from 'depictio-react-core';
import { useUiStore } from '../../store/useUiStore';

interface InspectorProvidersProps {
  /** Null while the `inspector_enabled` flag is off — which is what keeps the
   *  inspect action out of every component's chrome and stops renderers from
   *  publishing. `useInspectorChrome` builds it as `enabled ? {…} : null`, so
   *  this one value carries the flag; there is no separate `enabled` prop to
   *  fall out of step with it. */
  control: InspectorControl | null;
  children: React.ReactNode;
}

/**
 * The two contexts the inspector needs around the whole app: one so each
 * component's chrome can offer an "inspect" action, one so advanced-viz
 * renderers can publish their controls and data up to the panel.
 *
 * Mounted unconditionally — both take null to mean "no inspector", so the flag
 * is expressed as a value rather than as conditional JSX in two apps.
 */
const InspectorProviders: React.FC<InspectorProvidersProps> = ({ control, children }) => {
  const publishAdvancedVizExtras = useUiStore((s) => s.publishAdvancedVizExtras);
  return (
    <InspectorProvider value={control}>
      <AdvancedVizInspectorProvider value={control ? publishAdvancedVizExtras : null}>
        {children}
      </AdvancedVizInspectorProvider>
    </InspectorProvider>
  );
};

export default InspectorProviders;

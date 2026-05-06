/// <reference types="vite/client" />

// react-cytoscapejs ships no .d.ts. The runtime API is a thin React wrapper
// around cytoscape.js, so a permissive any-typed default export suffices.
declare module 'react-cytoscapejs' {
  import type { ComponentType } from 'react';
  const CytoscapeComponent: ComponentType<Record<string, unknown>>;
  export default CytoscapeComponent;
}

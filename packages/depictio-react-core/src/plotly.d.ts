// `plotly.js` ships no TS types and we don't depend on `@types/plotly.js` —
// at runtime vite's resolve.alias swaps the import for the prebuilt UMD
// bundle. Declare the module so `tsc` accepts `import Plotly from 'plotly.js'`
// in FigureRenderer; the call sites cast to the needed shape locally.
declare module 'plotly.js';

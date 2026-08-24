// Register the bundled Iconify icons.
//
// Import this once, first thing in an entry point. Without it `<Icon/>` falls
// back to fetching icon data from the public Iconify API, which the app's
// `connect-src 'self'` CSP blocks — every icon then renders as an empty box.
// That failure only shows up outside `vite dev`, which sends no CSP at all.
//
// The subset is generated from the source tree by scripts/generate-icon-subset.mjs,
// which `predev` / `prebuild` run automatically.

import { addCollection } from '@iconify/react';

import { iconCollections } from './generated/iconSubset';

for (const collection of iconCollections) {
  addCollection(collection);
}

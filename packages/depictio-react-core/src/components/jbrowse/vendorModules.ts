/**
 * Entry of the static runtime's `jbrowse` add-on (depictio/viewer/vite.static-jbrowse.config.ts).
 *
 * The add-on is the third-party half of the genome browser: JBrowse 2, MUI,
 * mobx and their adapters (~3.6 MB raw). The depictio half — JBrowseRenderer
 * and its helpers in depictio-react-core — stays in the base runtime, because
 * it shares stores and contexts (the highlight bus, the dashboard loading
 * provider, the genome-tracks store) with every other tile and must be the
 * same module instance as theirs.
 *
 * Every specifier the depictio half imports is listed here once, as a module
 * namespace. The base runtime aliases each of them to a forwarder
 * (`depictio/viewer/src/static-runtime/jbrowse/forward.ts`) that reads its namespace back from this map, so React is
 * the only thing the two halves share by reference: the add-on build takes it
 * as an external the runtime hands over (`static-runtime/jbrowse/vendor.ts`).
 *
 * Not here: the circular and breakpoint views (`@jbrowse/react-circular-
 * genome-view2`, `@jbrowse/react-app2`). They are opened from the tile's
 * "More views" menu, they would double the add-on, and the bundle does not
 * ship the data they read (the forwarder says so instead).
 */
import * as lgv from '@jbrowse/react-linear-genome-view2';
import * as configuration from '@jbrowse/core/configuration';
import * as ui from '@jbrowse/core/ui';
import * as util from '@jbrowse/core/util';
import * as jexlStrings from '@jbrowse/core/util/jexlStrings';
import * as simpleFeature from '@jbrowse/core/util/simpleFeature';
import * as Plugin from '@jbrowse/core/Plugin';
import * as BaseAdapter from '@jbrowse/core/data_adapters/BaseAdapter';
import * as TextSearchAdapterType from '@jbrowse/core/pluggableElementTypes/TextSearchAdapterType';
import * as BaseResults from '@jbrowse/core/TextSearch/BaseResults';
import * as embeddedCore from '@jbrowse/embedded-core';
import * as mst from '@jbrowse/mobx-state-tree';
import * as gtf from '@jbrowse/plugin-gtf';
import * as mui from '@mui/material';
import * as mobx from 'mobx';
import * as mobxReact from 'mobx-react';

export const modules: Record<string, Record<string, unknown>> = {
  '@jbrowse/react-linear-genome-view2': lgv,
  '@jbrowse/core/configuration': configuration,
  '@jbrowse/core/ui': ui,
  '@jbrowse/core/util': util,
  '@jbrowse/core/util/jexlStrings': jexlStrings,
  '@jbrowse/core/util/simpleFeature': simpleFeature,
  '@jbrowse/core/Plugin': Plugin,
  '@jbrowse/core/data_adapters/BaseAdapter': BaseAdapter,
  '@jbrowse/core/pluggableElementTypes/TextSearchAdapterType': TextSearchAdapterType,
  '@jbrowse/core/TextSearch/BaseResults': BaseResults,
  '@jbrowse/embedded-core': embeddedCore,
  '@jbrowse/mobx-state-tree': mst,
  '@jbrowse/plugin-gtf': gtf,
  '@mui/material': mui,
  mobx,
  'mobx-react': mobxReact,
};

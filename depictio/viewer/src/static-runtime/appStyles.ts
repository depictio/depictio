/**
 * The App's stylesheets, in their cascade order: Mantine's base first, its
 * extensions, the grid's, then the app's own. Imported by every entry of the
 * static runtime (the bundle's `appHost.tsx`, the report's `combined/main.tsx`)
 * so they cannot drift apart. An entry's own stylesheets (glass `layout.css`,
 * `report.css`) are imported after this module, so they override it.
 */
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/carousel/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/tiptap/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../styles/app.css';

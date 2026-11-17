/**
 * Stand-ins for the live project page's server-only parts in a static bundle.
 *
 * A bundle mounts the real `ProjectDetailApp` as its project page. Its
 * read-only, offline parts (the header, dashboards, workflows, the collections
 * table and viewer, the links and their map) answer from the manifest through
 * the api shim. What needs a server — editing (settings, links, tables,
 * coordinates, adding data), ingestion (reports, history, triggers, runs, the
 * timeline, "what changed"), Delta history and the previews that read object
 * storage — is hidden in a bundle by `useIsStaticBundle()`, and swapped for
 * these at build time (`projectServerParts.json`, read by
 * vite.static.config.ts and scripts/check-static-shim.mjs), so none of it is
 * compiled in: no code that could reach a server, and no bytes against the
 * runtime's budget.
 *
 * Every export of the swapped modules that an importer names must exist here
 * (rollup fails the build on a missing one); each renders nothing.
 */
import type React from 'react';

/** Any server-only component: nothing to draw offline. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Offline: React.FC<any> = () => null;

export default Offline;

// ProjectTimelinePanel.tsx, ProjectChangesPill.tsx, DeltaVersionHistory.tsx,
// ProjectIngestionTrigger.tsx, ProjectIngestionHistoryPanel.tsx, RunsPanel.tsx,
// addData/AddDataButton.tsx
export const ProjectTimelinePanel = Offline;
export const ProjectChangesPill = Offline;
export const DeltaVersionHistory = Offline;
export const ProjectIngestionTrigger = Offline;
export const IngestionRunDetails = Offline;
export const RunsPanel = Offline;
export const AddDataButton = Offline;
// LinkMappingInspector.tsx
export const LinkMappingInspector = Offline;
export const LinkMappingModal = Offline;
// AssetPreviews.tsx
export const ImagesPreview = Offline;
export const TreePreview = Offline;
export const TracksPreview = Offline;
export const LegacyTracksNotice = Offline;
export const GeoJsonPreview = Offline;

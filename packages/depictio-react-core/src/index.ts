/**
 * depictio-react-core — shared grid + renderer code for the Depictio SPA viewer
 * and the Dash custom-component package. Consumers import the high-level
 * components (DashboardGrid, ComponentRenderer) and the API helpers; renderers
 * are also exported in case a host wants to wire one up directly.
 */

// Realtime highlight keyframes (depictio-row-new / depictio-card-new). Imported
// once here so consumers don't need to add the stylesheet manually.
import './styles/realtime-highlight.css';

// Grid + top-level renderer
export { default as DashboardGrid } from './components/DashboardGrid';
export { default as ComponentRenderer } from './components/ComponentRenderer';
export { default as ErrorBoundary } from './components/ErrorBoundary';
export { default as ComponentSkeleton } from './components/ComponentSkeleton';
export type { SkeletonVariant } from './components/ComponentSkeleton';

// Dashboard-wide load registry: renderers report their status, the viewer's
// progress bar reads the aggregate. Absent provider → reporting is a no-op.
export {
  DashboardLoadingProvider,
  ComponentIndexContext,
  useReportLoadStatus,
  useDashboardLoadSummary,
  TRACKED_LOAD_TYPES,
} from './components/DashboardLoadingProvider';
export type {
  ComponentLoadStatus,
  DashboardLoadSummary,
} from './components/DashboardLoadingProvider';

// Per-type renderers (top-level)
export { default as FigureRenderer } from './components/FigureRenderer';
export { default as TableRenderer } from './components/TableRenderer';
export { default as ImageRenderer } from './components/ImageRenderer';
export { default as MapRenderer } from './components/MapRenderer';
export { default as TextRenderer } from './components/TextRenderer';
export { default as JBrowseRenderer } from './components/JBrowseRenderer';
export { default as MultiQCRenderer } from './components/MultiQCRenderer';

// Card helpers — exposed so the builder preview in `depictio/viewer` can
// render the same SecondaryMetrics strip the dashboard grid renders.
export { default as SecondaryMetrics } from './components/card/SecondaryMetrics';
export {
  BREAKDOWN_LAYOUTS,
  isBreakdownLayout,
  NUMERIC_LAYOUTS,
  isNumericLayout,
  STAT_LIST_LAYOUTS,
} from './components/card/SecondaryMetrics';
export type { SecondaryLayout } from './components/card/SecondaryMetrics';
export type {
  HistogramPayload,
  ThresholdPayload,
  CompletenessPayload,
  AttritionPayload,
  TrendPayload,
  UniquenessPayload,
} from './components/card/SecondaryMetrics';

// Interactive renderers
export { default as MultiSelectRenderer } from './components/interactive/MultiSelectRenderer';
export { default as RangeSliderRenderer } from './components/interactive/RangeSliderRenderer';
export { default as SliderRenderer } from './components/interactive/SliderRenderer';
export { default as DatePickerRenderer } from './components/interactive/DatePickerRenderer';
export { default as CheckboxSwitchRenderer } from './components/interactive/CheckboxSwitchRenderer';
export { default as SegmentedControlRenderer } from './components/interactive/SegmentedControlRenderer';
export { default as TimelineRenderer } from './components/interactive/TimelineRenderer';
// The one frame every interactive control renders inside — exported so the
// builder can label a component the way the viewer would.
export {
  INTERACTIVE_FRAME,
  InteractiveFrame,
  InteractiveTitle,
  defaultInteractiveTitle,
  interactiveTitle,
} from './components/interactive/frame';

// Layout helpers (filter sidebar grouping + top panel)
export { default as FilterPanel } from './components/interactive/FilterPanel';
export { FILTER_PANEL_RAIL_WIDTH } from './components/interactive/FilterPanel';
export type { FilterPanelProps } from './components/interactive/FilterPanel';
export { default as InteractiveGroupCard } from './components/InteractiveGroupCard';
// One swatch for every place a section is drawn — the two panel headers and the
// viewer's authoring UI — so a section named "QC" never looks different
// depending on where you meet it.
export { default as SectionIcon, sectionColorVar } from './components/SectionIcon';
export { default as TopPanel } from './components/TopPanel';
export { groupInteractiveComponents } from './utils/groupInteractive';
export type { InteractiveGroup } from './utils/groupInteractive';
export { extractLayoutItems, stripBoxPrefix } from './utils/leftPanelLayout';
export { countActiveFilters } from './activeFilters';
export {
  PANEL_TOGGLE_EVENTS,
  SIDEBAR_TOGGLE_EVENT,
  FILTER_PANEL_TOGGLE_EVENT,
  INSPECTOR_TOGGLE_EVENT,
  dispatchPanelToggle,
  PANEL_RESIZE_END_EVENT,
  beginPanelResize,
  endPanelResize,
  isPanelResizing,
} from './utils/panelToggle';
export type { PanelToggleDetail } from './utils/panelToggle';
// Advanced-viz ↔ inspector bridge. Deliberately a separate module from the
// renderers so importing it doesn't pull in the plotly-heavy lazy chunk.
export { AdvancedVizInspectorProvider } from './components/advanced_viz/AdvancedVizInspectorBridge';
export type { AdvancedVizInspectorPublisher } from './components/advanced_viz/AdvancedVizInspectorBridge';
export type { AdvancedVizExtrasPayload } from './components/advanced_viz/AdvancedVizExtras';
// The shared show-data grid, so the inspector can dock the same table the
// renderers' popovers show.
export { default as DataGridBody } from './components/data/DataGridBody';
export type { TierAnnotation } from './components/data/DataGridBody';
export { readMultiqcSelection } from './utils/multiqcSelection';
export type { MultiqcSelection } from './utils/multiqcSelection';

// MultiQC sub-renderers
export { default as MultiQCFigure } from './components/multiqc/MultiQCFigure';
export { default as MultiQCGeneralStats } from './components/multiqc/MultiQCGeneralStats';

// Chrome (per-component action toolbar)
export {
  ComponentChrome,
  MetadataPopover,
  MetadataBody,
  FullscreenButton,
  DownloadButton,
  ResetButton,
  InspectorProvider,
  useInspectorControl,
  actionsFor,
  wrapWithChrome,
  StaticBadgeProvider,
  StaticTierBadge,
  useIsStaticBundle,
} from './components/chrome';
export type {
  ComponentChromeProps,
  ChromeAction,
  InspectorControl,
  WrapWithChromeOpts,
  StaticTierEntry,
  StaticTierMap,
} from './components/chrome';
// Tier badge vocabulary — shared between the in-bundle StaticTierBadge and the
// viewer's Export-static preflight modal. Aliased to avoid generic names in
// the package namespace. Note 'live' is absent (see StaticBadgeContext).
export {
  BADGE_LABEL as STATIC_TIER_BADGE_LABEL,
  BADGE_COLOR as STATIC_TIER_BADGE_COLOR,
  // Curated per-verdict sentence — the modal promises what the badge will say.
  staticTierExplanation,
} from './components/chrome/StaticBadgeContext';

// API surface — fetchers, payload types, filter types
export {
  fetchDashboard,
  fetchAllDashboards,
  fetchFloatingComponents,
  fetchSpecs,
  fetchUniqueValues,
  fetchBreakdown,
  fetchCardMetric,
  fetchColumnRange,
  fetchComponentData,
  bulkComputeCards,
  renderFigure,
  renderTable,
  fetchImagePaths,
  renderMap,
  fetchJBrowseSession,
  renderMultiQC,
  renderMultiQCGeneralStats,
  fetchServerStatus,
  fetchPublicConfig,
  fetchCurrentUser,
  updateTab,
  deleteTab,
  reorderTabs,
  createTab,
  // Builder helpers
  fetchWorkflowsForUser,
  fetchProjectFromDashboard,
  fetchDeltaShape,
  fetchDataCollectionConfig,
  fetchDataCollectionPreview,
  previewFigure,
  previewMultiQC,
  fetchMultiQCBuilderOptions,
  analyzeFigureCode,
  fetchFigureParameterDiscovery,
  fetchFigureVisualizationList,
  upsertComponent,
  saveDashboardNotes,
  // Auth helpers (React /auth page)
  fetchAuthStatus,
  loginUser,
  registerUser,
  createTemporaryUser,
  getAnonymousSession,
  startGoogleOAuth,
  handleGoogleCallback,
  exchangeMagicToken,
  persistSession,
  clearSession,
  validateSession,
  authFetch,
  refreshAccessToken,
  startSessionKeepAlive,
  stopSessionKeepAlive,
  // Dashboard management
  listDashboards,
  listProjects,
  createDashboard,
  editDashboard,
  deleteDashboard,
  duplicateDashboard,
  importDashboardJson,
  importDashboardYaml,
  validateDashboardJson,
  exportDashboardJson,
  // Serverless static export
  preflightStaticExport,
  dispatchStaticExport,
  pollStaticExport,
  downloadStaticExport,
  // Project management
  fetchProject,
  fetchIngestionReport,
  fetchIngestionHealth,
  fetchDataCollectionFiles,
  createProject,
  updateProject,
  deleteProject,
  toggleProjectVisibility,
  updateProjectPermissions,
  importProjectZip,
  exportProjectZip,
  fetchUserByEmail,
  fetchMultiQCByDataCollection,
  renameDataCollection,
  deleteDataCollection,
  createDataCollectionFromUpload,
  // Admin
  listAllUsers,
  deleteUser,
  setUserAdmin,
  listAllProjects,
  listAllDashboards,
  listExampleProjects,
  cleanExampleProjects,
  // Admin monitoring (Log & Task)
  fetchMonitoringTasks,
  fetchMonitoringTask,
  fetchIngestionRuns,
  fetchIngestionRun,
  fetchAppLogs,
  fetchMonitoringHealth,
  fetchLogCaptureLevel,
  setLogCaptureLevel,
  // Profile + CLI tokens
  fetchCurrentUserFull,
  editPassword,
  listLongLivedTokens,
  createLongLivedToken,
  deleteLongLivedToken,
  generateAgentConfig,
  // Cross-DC links
  listProjectLinks,
  createProjectLink,
  updateProjectLink,
  deleteProjectLink,
  listLinkResolvers,
  fetchMultiQCSampleMappings,
  // MultiQC management (multipart uploads)
  createMultiQCDataCollection,
  checkMultiQCUniformity,
  appendMultiQCFiles,
  replaceMultiQCFiles,
  clearMultiQCDC,
  // Table DC management (multipart uploads)
  appendTableFiles,
  replaceTableFiles,
  clearTableDC,
  // Advanced viz
  fetchAdvancedVizKinds,
  fetchAdvancedVizData,
  fetchPolarsSchema,
  fetchVizSuggestions,
  fetchPhylogenyNewick,
  dispatchComputeEmbedding,
  pollComputeEmbedding,
  dispatchComplexHeatmap,
  pollComplexHeatmap,
  dispatchUpset,
  pollUpset,
  // Catalog compose + preview
  fetchCatalogCompose,
  fetchCatalogPreviewPayload,
} from './api';
export type {
  FloatingComponent,
  FloatingComponentsResponse,
  TableMutationResult,
  RoleDtypeSpec,
  IngestionReport,
  IngestionDataCollection,
  IngestionRun,
  IngestionSummary,
  RegisteredFile,
  VizKindSuggestion,
  VizSuggestionsResponse,
  CatalogRender,
  CatalogOutputMatch,
  CatalogModule,
  CatalogComposeResponse,
  CatalogPreviewRender,
  CatalogPreviewPayload,
  BreakdownPayloadDTO,
} from './api';
// Selection-as-filter helpers (Plotly/AG Grid → InteractiveFilter)
export {
  extractScatterSelection,
  extractRowSelection,
  mergeFiltersBySource,
  clearFiltersBySource,
  hasSelectionFilters,
  enrichFilterWithDcId,
} from './selection';

// Map panel: a map lifted out of the grid, available from every tab as a
// floating card or as a dock under the filter panel. Mount both shells — each
// renders nothing unless the panel is in its mode.
// Consumers that draw their own Plotly map (the builder / project previews)
// need this too — plotly leaves every map's basemap credit expanded on first
// paint. See the helper's own docstring.
export { collapseMapAttribution } from './components/map/collapseMapAttribution';
export { default as MapPanelControl } from './components/mapPanel/MapPanelControl';
export type { MapPanelControlProps } from './components/mapPanel/MapPanelControl';
export { default as MapPanelSurface } from './components/mapPanel/MapPanelSurface';
export type { MapPanelSurfaceProps } from './components/mapPanel/MapPanelSurface';
export { default as MapPanelDock } from './components/mapPanel/MapPanelDock';
export type { MapPanelDockProps } from './components/mapPanel/MapPanelDock';
export { useMapPanel } from './components/mapPanel/useMapPanel';
export type { MapPanel, UseMapPanelOptions } from './components/mapPanel/useMapPanel';
export type {
  MapPanelMode,
  MapPanelCardSize,
  MapPanelState,
} from './components/mapPanel/useMapPanelState';
export {
  readFloatingFilters,
  writeFloatingFilters,
  clearFloatingFilters,
  persistableFloatingFilters,
} from './floatingFilters';
export type { FloatingFilterPayload } from './floatingFilters';

// Cross-DC available-values intersection (powers greying-out unavailable
// options in interactive filter dropdowns).
export {
  AvailableFilterValuesProvider,
  useAvailableSet,
} from './availableValues';

// Real-time event subscription (WebSocket /events/ws)
export { useDataCollectionUpdates, useMonitoringEvents, ADMIN_MONITORING_CHANNEL } from './realtime';
export type {
  RealtimeStatus,
  RealtimeMode,
  RealtimeEvent,
  MonitoringLiveEvent,
} from './realtime';
export { default as RealtimeIndicator } from './components/RealtimeIndicator';
export { useRealtimeJournal } from './hooks/useRealtimeJournal';
export type { RealtimeJournalEntry } from './hooks/useRealtimeJournal';
export { batchIdsFromPayload } from './highlight';
export type { ActiveHighlight } from './highlight';

// Render-fetch queue. Apps that own the filter state call
// ``bumpFetchGeneration`` when it changes, so requests queued for the previous
// filter are dropped instead of running against a question nobody is asking.
export {
  bumpFetchGeneration,
  currentFetchGeneration,
  fetchQueueState,
  isStaleFetch,
  setFetchConcurrency,
  StaleFetchError,
} from './fetchQueue';

export type {
  StoredMetadata,
  DashboardData,
  FilterSectionSpec,
  DashboardSummary,
  InteractiveFilter,
  InteractiveFilterSource,
  BulkComputeResponse,
  FigureResponse,
  TableResponse,
  JBrowseSessionResponse,
  ServerStatusResponse,
  PublicConfigResponse,
  CurrentUser,
  UpdateTabPayload,
  TabOrderEntry,
  WorkflowEntry,
  DcShapeResponse,
  PreviewResult,
  FigurePreviewRequest,
  MultiQCPreviewRequest,
  MultiQCBuilderOptions,
  CodeAnalysis,
  FigureParameterSpec,
  FigureParameterType,
  FigureParameterCategory,
  FigureVisualizationGroup,
  FigureVisualizationDefinition,
  FigureVisualizationSummary,
  SaveComponentOptions,
  // Auth types
  AuthMode,
  AuthStatusResponse,
  SessionPayload,
  RegisterResult,
  GoogleCallbackResult,
  // Dashboard management types
  DashboardListEntry,
  DashboardPermissions,
  DashboardPermissionsUser,
  ProjectListEntry,
  CreateDashboardInput,
  EditDashboardInput,
  ImportDashboardOptions,
  ImportDashboardResult,
  // Serverless static export types
  StaticExportTierRow,
  StaticExportLinkRow,
  StaticExportPreflight,
  StaticExportResult,
  StaticExportJob,
  // Project management types
  CreateProjectInput,
  CreateProjectResult,
  EditProjectInput,
  ProjectPermissionsInput,
  MultiQCReportSummary,
  MultiQCReportsList,
  CreateDataCollectionUploadInput,
  CreateDataCollectionResult,
  // Admin types
  AdminUser,
  AdminProject,
  AdminDashboard,
  ExampleProject,
  // Admin monitoring types
  MonitoringTaskEvent,
  MonitoringIngestionRun,
  MonitoringAppLog,
  MonitoringHealth,
  // Profile + CLI token types
  ProfileUser,
  CliToken,
  CreatedToken,
  CliAgentConfig,
  // Link types
  LinkResolverName,
  LinkTargetType,
  DCLink,
  DCLinkConfig,
  CreateLinkInput,
  UpdateLinkInput,
  ResolverInfo,
  // MultiQC management types
  CreateMultiQCDCInput,
  MultiQCMutationResult,
  MultiQCUniformityCheckResult,
  // Advanced viz types
  AdvancedVizKind,
  AdvancedVizKindDescriptor,
  AdvancedVizDataResponse,
} from './api';

// Anonymous browser telemetry — shared with the Tools Studio, which aliases this
// package in its Vite config so both apps use one consent implementation.
export { capture, initTelemetry, isOptedOut, setOptOut } from './telemetry';
export type { TelemetryConfig } from './telemetry';

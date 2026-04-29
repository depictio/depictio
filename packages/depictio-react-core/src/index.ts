/**
 * depictio-react-core — shared grid + renderer code for the Depictio SPA viewer
 * and the Dash custom-component package. Consumers import the high-level
 * components (DashboardGrid, ComponentRenderer) and the API helpers; renderers
 * are also exported in case a host wants to wire one up directly.
 */

// Grid + top-level renderer
export { default as DashboardGrid } from './components/DashboardGrid';
export { default as ComponentRenderer } from './components/ComponentRenderer';
export { default as ErrorBoundary } from './components/ErrorBoundary';

// Per-type renderers (top-level)
export { default as FigureRenderer } from './components/FigureRenderer';
export { default as TableRenderer } from './components/TableRenderer';
export { default as ImageRenderer } from './components/ImageRenderer';
export { default as MapRenderer } from './components/MapRenderer';
export { default as JBrowseRenderer } from './components/JBrowseRenderer';
export { default as MultiQCRenderer } from './components/MultiQCRenderer';

// Interactive renderers
export { default as MultiSelectRenderer } from './components/interactive/MultiSelectRenderer';
export { default as RangeSliderRenderer } from './components/interactive/RangeSliderRenderer';
export { default as SliderRenderer } from './components/interactive/SliderRenderer';
export { default as DatePickerRenderer } from './components/interactive/DatePickerRenderer';
export { default as CheckboxSwitchRenderer } from './components/interactive/CheckboxSwitchRenderer';
export { default as SegmentedControlRenderer } from './components/interactive/SegmentedControlRenderer';

// MultiQC sub-renderers
export { default as MultiQCFigure } from './components/multiqc/MultiQCFigure';
export { default as MultiQCGeneralStats } from './components/multiqc/MultiQCGeneralStats';

// Chrome (per-component action toolbar)
export {
  ComponentChrome,
  MetadataPopover,
  FullscreenButton,
  DownloadButton,
  ResetButton,
  actionsFor,
  wrapWithChrome,
} from './components/chrome';
export type {
  ComponentChromeProps,
  ChromeAction,
  WrapWithChromeOpts,
} from './components/chrome';

// API surface — fetchers, payload types, filter types
export {
  fetchDashboard,
  fetchAllDashboards,
  fetchSpecs,
  fetchUniqueValues,
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
  analyzeFigureCode,
  fetchFigureParameterDiscovery,
  fetchFigureVisualizationList,
  upsertComponent,
  // Auth helpers (React /auth page)
  fetchAuthStatus,
  loginUser,
  registerUser,
  createTemporaryUser,
  getAnonymousSession,
  startGoogleOAuth,
  handleGoogleCallback,
  persistSession,
  clearSession,
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
  // Project management
  fetchProject,
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
  // Admin
  listAllUsers,
  deleteUser,
  setUserAdmin,
  listAllProjects,
  listAllDashboards,
  // Profile + CLI tokens
  fetchCurrentUserFull,
  editPassword,
  listLongLivedTokens,
  createLongLivedToken,
  deleteLongLivedToken,
  generateAgentConfig,
  upgradeToTemporaryUser,
} from './api';
export type {
  StoredMetadata,
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  BulkComputeResponse,
  FigureResponse,
  TableResponse,
  JBrowseSessionResponse,
  ServerStatusResponse,
  CurrentUser,
  UpdateTabPayload,
  TabOrderEntry,
  WorkflowEntry,
  DcShapeResponse,
  PreviewResult,
  FigurePreviewRequest,
  MultiQCPreviewRequest,
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
  // Project management types
  CreateProjectInput,
  CreateProjectResult,
  EditProjectInput,
  ProjectPermissionsInput,
  MultiQCReportSummary,
  MultiQCReportsList,
  // Admin types
  AdminUser,
  AdminProject,
  AdminDashboard,
  // Profile + CLI token types
  ProfileUser,
  CliToken,
  CreatedToken,
  CliAgentConfig,
} from './api';

/**
 * depictio-react-core — shared grid + renderer code for the Depictio SPA viewer
 * and the Dash custom-component package. Consumers import the high-level
 * components (DashboardGrid, ComponentRenderer) and the API helpers; renderers
 * are also exported in case a host wants to wire one up directly.
 */

// Realtime highlight keyframes (depictio-row-new / depictio-card-new). Imported
// once here so consumers don't need to add the stylesheet manually.
import './styles/realtime-highlight.css';
// Before any Plot mounts: re-attach Plotly listeners after StrictMode's remount.
import './plotlyStrictMode';

// Grid + top-level renderer
export { default as DashboardGrid, SectionSummary } from './components/DashboardGrid';
export type { ComponentSection } from './utils/groupInteractive';
export { default as PersistentSectionsHost } from './components/PersistentSectionsHost';
export type { PersistentSectionsHostProps } from './components/PersistentSectionsHost';
// The grid's own geometry + per-type default box, for consumers that render a
// single component outside a grid and want the size it would really have.
export {
  GRID_COLS,
  GRID_ROW_HEIGHT,
  GRID_ROW_GAP,
  gridBoxHeight,
  defaultLayoutForType,
} from './api';
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
export { default as Glyph, glyphColorVar, isImagePath, isMultiqcIcon, themedIconSrc } from './components/Glyph';
export { TabLinkContext, tabLinkKey, useTabLinkResolver } from './components/tabLinks';
export type { TabLinkResolver, TabLinkTarget } from './components/tabLinks';
export {
  groupTabs,
  sameTabGroup,
  tabGroupNames,
  tabGroupOf,
  tabIdsInGroup,
  tabOrderAfterGroupMove,
  tabOrderAfterRegroup,
  tabOrderEntries,
} from './components/tabGroups';
export type { EditableTab, GroupableTab, TabGroup } from './components/tabGroups';
export { tabDisplayName, tabFamilyOf } from './components/tabFamily';
export type { FamilyTab } from './components/tabFamily';
export { canCopyToTab, copyComponentToTab } from './components/copyToTab';
export type { CopyToTabInput } from './components/copyToTab';
export { parseBlocks } from './components/blockMarkdown';
export type { Block as MarkdownBlock } from './components/blockMarkdown';
export { MARKDOWN_CHEATSHEET } from './components/markdownCheatsheet';
export type {
  MarkdownExample,
  MarkdownExampleGroup,
  MarkdownRendering,
} from './components/markdownCheatsheet';
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
// Card styles: the grid, the editor and the card builder resolve a card's style
// against its section's through the same helpers.
export {
  CARD_VARIANTS,
  normalizeCardVariant,
  resolveCardVariant,
  withSectionCardVariant,
  variantForPick,
  compactKeepsStrip,
  stripIsMinimal,
} from './components/cardVariant';
export type { CardVariant } from './components/cardVariant';
// Figure styles: same rule, for a figure's `figure_style` and its section's.
export {
  FIGURE_STYLES,
  normalizeFigureStyle,
  resolveFigureStyle,
  withSectionFigureStyle,
  withSectionStyles,
  figureStyleForPick,
  figurePlotConfig,
} from './components/figureStyle';
export type { FigureStyle } from './components/figureStyle';
export { default as FigureHeader } from './components/FigureHeader';
// Highlights: another tab's figure shown again (component_type 'highlight').
export {
  canHighlight,
  findHighlightSource,
  highlightMetadata,
  highlightOnTab,
  highlightSourceRef,
  highlightStyleRequest,
  resolveHighlightTab,
} from './components/highlightTile';
export type { HighlightOnTabInput, HighlightRef } from './components/highlightTile';
export type { FigureHeaderProps } from './components/FigureHeader';
export type {
  HistogramPayload,
  ThresholdPayload,
  CompletenessPayload,
  AttritionPayload,
  TrendPayload,
  UniquenessPayload,
  // Exported for the same reason as the rest: a consumer that computes these
  // payloads itself (Tool Studio, with no backend) has to name their shapes.
  BreakdownPayload,
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
export { default as SelectionGroupsPanel } from './components/interactive/SelectionGroupsPanel';
export type { SelectionGroupsPanelProps } from './components/interactive/SelectionGroupsPanel';
export { SaveGroupContext } from './components/chrome/SaveGroupAction';
export type { SaveGroupApi } from './components/chrome/SaveGroupAction';
export { default as InteractiveGroupCard } from './components/InteractiveGroupCard';
// One swatch for every place a section is drawn — the two panel headers and the
// viewer's authoring UI — so a section named "QC" never looks different
// depending on where you meet it.
export { default as SectionIcon, sectionColorVar } from './components/SectionIcon';
// The section chrome itself, for surfaces that show a section without a grid
// behind it (the dashboard Guide's demo).
export {
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
} from './components/SectionAccordion';
export { default as TopPanel } from './components/TopPanel';
export { groupInteractiveComponents } from './utils/groupInteractive';
export type { InteractiveGroup } from './utils/groupInteractive';

// Filter bars: a grid section drawn as one compact row of its interactive
// components (`display: 'strip'`, filtering the tab), or a section of tiles
// with a bar of its own (`filter_bar`, filtering that section only). The
// placement rules are exported so the apps route those components out of the
// filter panel by the same predicate the grid uses to draw them, and the
// scoping rules so every fetch applies the same "which filters reach which
// component".
export {
  EmptyBar,
  FilterStrip,
  FilterStripSection,
  SectionFilterBar,
} from './components/interactive/strip/FilterStrip';
export type {
  FilterStripProps,
  FilterStripSectionProps,
  FilterStripVariant,
  SectionFilterBarProps,
} from './components/interactive/strip/FilterStrip';
export {
  SECTION_BAR_DEFAULT_VISIBLE,
  barSectionNames,
  hasSectionBar,
  isBarMember,
  isBarSection,
  isStripSection,
  partitionBarMembers,
  sectionBarNames,
  sectionRuns,
  stripControlKind,
  stripLabel,
  stripShowsIcon,
  visibleFilterCount,
} from './components/interactive/strip/stripLayout';
export type { StripControlKind } from './components/interactive/strip/stripLayout';
export {
  NO_FILTER_SCOPES,
  activeFilterSignature,
  filtersInScope,
  mergeFilterScopes,
  planScopedRequests,
  scopedFilterIds,
  sectionFilterScopes,
  sectionScopeKey,
} from './filterScope';
export type { FilterScopes, ScopedRequest } from './filterScope';
export {
  MAX_STRIP_CHIPS,
  MAX_STRIP_SEGMENTS,
  categoricalDisplay,
  chipSelectionMode,
  filterEvent,
  orderCategoricalOptions,
  selectedValues,
  toggleChip,
} from './components/interactive/categoricalOptions';
export { useColumnRange, useUniqueValues } from './components/interactive/useInteractiveData';

// Category colours (`DashboardData.category_colors`): one categorical value,
// one colour, on every surface. The pure resolver is what the figure code
// shares with the filter bar; the hook binds it to the dashboard and theme.
export {
  NEUTRAL_CATEGORY_COLOR,
  categoryColor,
  categoryColorMap,
  dashboardColorway,
  hasPinnedColors,
  pinnedCategoryColor,
  pinnedCategoryDots,
  sortCategoryValues,
} from './categoryColors';
export type { CategoryColorSource } from './categoryColors';
export {
  CategoryColorsContext,
  useCategoryColorMap,
  useCategoryColorSource,
  useCategoryDotColors,
  useCategoryPalette,
} from './hooks/useCategoryColors';
export { extractLayoutItems, stripBoxPrefix } from './utils/leftPanelLayout';
export { countActiveFilters } from './activeFilters';
export {
  PANEL_TOGGLE_EVENTS,
  SIDEBAR_TOGGLE_EVENT,
  FILTER_PANEL_TOGGLE_EVENT,
  ANALYSIS_PANEL_TOGGLE_EVENT,
  INSPECTOR_TOGGLE_EVENT,
  dispatchPanelToggle,
  PANEL_RESIZE_END_EVENT,
  beginPanelResize,
  endPanelResize,
  isPanelResizing,
} from './utils/panelToggle';
export type { PanelToggleDetail } from './utils/panelToggle';
export { OPEN_RUN_PARAMETERS_EVENT, openRunParameters } from './utils/runParameters';
export type { OpenRunParametersDetail } from './utils/runParameters';
// Advanced-viz ↔ inspector bridge. Deliberately a separate module from the
// renderers so importing it doesn't pull in the plotly-heavy lazy chunk.
export { AdvancedVizInspectorProvider } from './components/advanced_viz/AdvancedVizInspectorBridge';
export type { AdvancedVizInspectorPublisher } from './components/advanced_viz/AdvancedVizInspectorBridge';
export type { AdvancedVizExtrasPayload } from './components/advanced_viz/AdvancedVizExtras';
// Advanced-viz config write-back. Separate module for the same reason as the
// inspector bridge: a provider can be mounted without the lazy renderer chunk.
export { AdvancedVizConfigDraftProvider } from './components/advanced_viz/AdvancedVizConfigDraft';
export type {
  VizConfigDraftSink,
  VizConfigPatch,
} from './components/advanced_viz/AdvancedVizConfigDraft';
// The phylogenetic viz's sources and ranks, for the builder. Pure modules, so
// the same light-import reasoning applies.
export {
  abundanceRankCoverage,
  phyloSourcePatch,
  preferredTipMetadata,
  tipLabelColumn,
} from './components/advanced_viz/phylo/sources';
export type { PhyloDcRef, PhyloSource } from './components/advanced_viz/phylo/sources';
export { orderTaxonomicRanks } from './components/advanced_viz/phylo/view';
export { rankChoices as phyloRankChoices } from './components/advanced_viz/phylo/view';
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
  CatalogButton,
  CatalogOrigin,
  FullscreenButton,
  DownloadButton,
  ResetButton,
  LoadAllButton,
  SelectionHintAction,
  InspectorProvider,
  useInspectorControl,
  actionsFor,
  canDuplicate,
  wrapWithChrome,
  EDIT_MENU_STYLE,
  FULLSCREEN_EXIT_ICON,
  LOAD_ALL_ACTIVE_ICON,
  TILE_ACTION_STYLE,
} from './components/chrome';
export type {
  ComponentChromeProps,
  ChromeAction,
  EditMenuStyleKey,
  InspectorControl,
  LoadAllState,
  TileActionStyle,
  TileActionStyleKey,
  WrapWithChromeOpts,
} from './components/chrome';

// API surface — fetchers, payload types, filter types
export {
  fetchDashboard,
  fetchAllDashboards,
  fetchFloatingComponents,
  fetchCrossTabComponents,
  fetchSpecs,
  fetchUniqueValues,
  fetchBreakdown,
  fetchCardMetric,
  fetchCardHeroValue,
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
  uploadDashboardLogo,
  updateDashboardAppearance,
  // Instance branding (admin panel)
  fetchBrandingAdmin,
  updateBrandingAdmin,
  resetBrandingAdmin,
  fetchBrandPresets,
  resolveBrandTheme,
  uploadBrandingLogo,
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
  // Admin backup & restore
  listBackups,
  getBackupSchedule,
  updateBackupSchedule,
  createBackup,
  downloadBackup,
  uploadBackup,
  validateBackup,
  restoreBackup,
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
  fetchLinkMappingPreview,
  // Funnel filtering (issue #939)
  fetchFunnelValues,
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
  AdminBrandingState,
  BulkComputeOptions,
  BrandPreset,
  FloatingComponent,
  FloatingComponentsResponse,
  PersistentSection,
  CrossTabComponentsResponse,
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
  CatalogSource,
  FigureStyleRequest,
} from './api';
// Selection-as-filter helpers (Plotly/AG Grid → InteractiveFilter)
export {
  extractScatterSelection,
  extractRowSelection,
  mergeFiltersBySource,
  clearFiltersBySource,
  hasSelectionFilters,
  enrichFilterWithDcId,
  supportsSelectionGrouping,
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
export { useCrossTabComponents } from './hooks/useCrossTabComponents';
export type { CrossTabComponents } from './hooks/useCrossTabComponents';
export type {
  MapPanelMode,
  MapPanelCardSize,
  MapPanelState,
} from './components/mapPanel/useMapPanelState';
export {
  readCrossTabFilters,
  writeCrossTabFilters,
  clearCrossTabFilters,
  persistableCrossTabFilters,
} from './crossTabFilters';
export type { CrossTabFilterPayload } from './crossTabFilters';
export {
  readEditorFilters,
  writeEditorFilters,
  clearEditorFilters,
} from './editorFilters';
export type { EditorFilterPayload } from './editorFilters';

// Selection groups: named, colored snapshots of selections ("select & compare")
export {
  GROUP_FILTER_SOURCE,
  GROUP_FILTER_INDEX_PREFIX,
  MAX_GROUP_VALUES,
  GROUPING_COLOR,
  useGroupingColor,
  useGroupingColorVar,
  COLOR_BY_NONE,
  resolveGroupRender,
  selectableSelectionFilters,
  groupFromSelectionFilter,
  groupsToFilters,
  groupsRenderPayload,
  nextGroupColor,
  uniqueGroupName,
  defaultGroupName,
  readSelectionGroups,
  writeSelectionGroups,
} from './selectionGroups';
export type {
  SelectionGroup,
  SelectionGroupsPayload,
  GroupRenderDef,
  GroupRenderState,
  ColorByState,
  GroupingDisplay,
} from './selectionGroups';
export { groupBadgeLabel, summarizeGroupStatus } from './groupStatus';
export type { GroupStatusEntry, GroupStatusSummary } from './groupStatus';
export { useSelectionGroups } from './hooks/useSelectionGroups';
export type { SelectionGroupsApi } from './hooks/useSelectionGroups';
export { useCategoricalColumns, useColorByColumnRender } from './hooks/useColorByColumns';
export type { ColorByColumn, ColorByColumnRender } from './hooks/useColorByColumns';
export type { GroupSummaryRow } from './components/interactive/ActiveFilterSummary';

// Cross-DC available-values intersection (powers greying-out unavailable
// options in interactive filter dropdowns) + the funnel-filtering layer on
// top of it (issue #939).
export {
  AvailableFilterValuesProvider,
  useAvailableSet,
  useFunnelState,
} from './availableValues';
export type { FunnelComponentState } from './availableValues';
export { default as FunnelView } from './components/interactive/FunnelView';
export type { FunnelViewProps } from './components/interactive/FunnelView';

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

// Dashboard-wide UI scale (font-size) preference. The viewer app owns the
// provider; Plotly/AG Grid renderers consume the value for their non-Mantine
// pixel metrics.
export { UiScaleContext, useUiScale, UI_SCALE_STEPS, UI_SCALE_DEFAULT } from './uiScale';

// Brand theme (#397): the shared shape and its mapping onto Mantine. Lives
// here rather than in the viewer so every entry point that mounts its own
// MantineProvider (catalog preview, dev harnesses) can build the same theme.
export {
  BRAND_PALETTES,
  brandAccent,
  BrandingContext,
  brandCssVariablesResolver,
  buildDepictioTheme,
  depictioTheme,
  isEmptyBrandTheme,
  isHexColor,
  mergeBrandThemes,
  isMantinePaletteName,
  resolveBrandLogo,
  useBrandAccent,
  useBrandAccents,
  useBranding,
} from './brandTheme';
export type {
  BrandPlots,
  BrandRole,
  BrandSurfaces,
  BrandTheme,
  DepictioThemeOptions,
  LogoMode,
  TintMode,
} from './brandTheme';

// Brand theme editor + live preview, shared by the /admin Branding panel and
// the per-dashboard appearance panel — the two levels edit the same model, so
// they share the controls rather than mirroring each other.
export {
  BrandScope,
  BrandThemeForm,
  BrandThemePreview,
  PLOT_TEMPLATE_OPTIONS,
  useBrandScopeAttributes,
  useResolvedBrandTheme,
} from './components/branding';
export type {
  BrandScopeAttributes,
  BrandFormScope,
  BrandThemeFormProps,
  BrandThemePreviewProps,
} from './components/branding';

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
  CategoryColors,
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
  // Admin backup & restore types
  AdminBackupEntry,
  BackupScheduleStatus,
  BackupCollectionValidation,
  BackupValidationResult,
  BackupCreateResult,
  BackupUploadResult,
  BackupRestoreResult,
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
  LinkMappingPreviewRow,
  LinkMappingPreviewResponse,
  // Funnel filtering types (issue #939)
  FunnelTargetResult,
  FunnelStage,
  FunnelValuesResponse,
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

export { COMPONENT_TYPE_VISUALS, componentTypeVisual } from './componentTypeMeta';
export type { ComponentTypeVisual } from './componentTypeMeta';
export { brandColors } from './brandColors';
export { catalogToolUrl } from './catalogLinks';

// Shareable listing views: the /dashboards and /projects pages encode their
// filters into the URL, and both narrow on the template a project came from.
export {
  matchesTemplateFilter,
  parseTemplateOrigin,
  templateFilterValues,
} from './templateFilter';
export type { ParsedTemplate } from './templateFilter';
export {
  asEnum,
  asList,
  asScalar,
  decodeListingParams,
  encodeListingParams,
} from './listingUrlState';
export type { ListingParams } from './listingUrlState';
export {
  ADMIN_TABS,
  EMPTY_INGESTION_FILTERS,
  INGESTION_STATUSES,
  MONITORING_PANES,
  adminUrl,
  parseAdminUrl,
} from './adminUrlState';
export type {
  AdminRoute,
  AdminTab,
  IngestionFilters,
  IngestionStatusFilter,
  MonitoringPane,
  ParsedAdminUrl,
} from './adminUrlState';
export { Z_LAYERS } from './zLayers';
// The dashboard Guide: what it says about a tab, read from the dashboard.
export {
  buildGuideModel,
  GUIDE_ACTIONS,
  GUIDE_EDIT_ACTIONS,
  resolveGuideSettings,
  tileActions,
} from './guide/guideModel';
export {
  actionsTileRank,
  analysisCardRank,
  analysisFigureRank,
  analysisTableRank,
  demoSectionsOf,
  familyOrder,
  figureDrawsGroups,
  foldableSectionsOf,
  hasCards,
  pickFilterDemo,
  pickFromFamily,
  selectionColumnOf,
} from './guide/demoSources';
export type {
  GuideDemoSection,
  GuideFamilyDoc,
  GuideFamilyPick,
  GuideFilterDemoPick,
} from './guide/demoSources';
// Tiles drawn a second time elsewhere on the page (the Guide) measure under a
// scope of their own, so the canvas grid never takes their heights.
export { AutofitScope } from './components/autofit';
export {
  editActionsFor,
  GUIDE_TILE_TYPES,
  ownControlsFor,
  rowActionsFor,
} from './guide/tileActionCatalog';
export type {
  GuideEditAction,
  GuideOwnControl,
  GuideRowAction,
  GuideTileType,
} from './guide/tileActionCatalog';
export type {
  GuideAction,
  GuideActionKey,
  GuideEditActionKey,
  GuideFilterSection,
  GuideGridSection,
  GuideModel,
  GuideModelInput,
  GuideSelectionKind,
  GuideSelectionSource,
  GuideSettings,
  GuideTab,
  GuideTabGroup,
} from './guide/guideModel';

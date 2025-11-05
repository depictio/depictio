⏺ Based on our work getting the standalone Iris dashboard functional, here's a comprehensive summary of requirements:

  Code Perspective (Modularization)

  Core Dependencies from Main Codebase:
  - build_interactive_component() from depictio/dash/modules/interactive_component/utils.py
  - build_card() from depictio/dash/modules/card_component/utils.py
  - build_figure() from depictio/dash/modules/figure_component/utils.py
  - register_callbacks_card_component() from depictio/dash/modules/card_component/frontend.py
  - register_callbacks_figure_component() from depictio/dash/modules/figure_component/frontend.py

  Critical Infrastructure:
  1. Data Loading Bypass: Monkey-patched load_deltatable_lite() wrapper to intercept API/S3 calls
    - Replaces Delta table loading with pre-loaded DataFrame
    - Maintains filtering logic from original function
    - Returns data in expected format (Polars DataFrame)
  2. Required Layout Components:
    - interactive-values-store (dcc.Store) - aggregates filter values
    - local-store (dcc.Store) - required by figure callback State dependencies
    - Pattern-matching stored-metadata-component for each card/figure
  3. Callback Architecture:
    - Custom store population callback (aggregates interactive component values)
    - Reused card/figure callbacks from main codebase
    - Proper callback registration order matters
  4. Theme Support:
    - dmc.add_figure_templates() must be called at app startup
    - Registers Mantine templates (mantine_light, mantine_dark) with Plotly

  Metadata Requirements

  Component Metadata Structure (exported from MongoDB):
  {
    "interactive": [
      {
        "index": "uuid",
        "column_name": "column_name",
        "interactive_component_type": "RangeSlider|MultiSelect",
        "wf_id": {"$oid": "..."},
        "dc_id": {"$oid": "..."},
        "column_type": "float64|object",
        "min": ..., "max": ...,  // for RangeSlider
        "options": [...]          // for MultiSelect
      }
    ],
    "card": [
      {
        "index": "uuid",
        "column_name": "column_name",
        "aggregation": "average|min|count|median|nunique",
        "wf_id": {"$oid": "..."},
        "dc_id": {"$oid": "..."},
        "column_type": "float64|object"
      }
    ],
    "figure": [
      {
        "index": "uuid",
        "visu_type": "box|histogram|scatter|...",
        "dict_kwargs": {...},  // Plotly figure parameters
        "wf_id": {"$oid": "..."},
        "dc_id": {"$oid": "..."}
      }
    ]
  }

  Data Collection Config:
  dc_config = {
      "type": "table",
      "metatype": "standalone"
  }

  Column Specifications (for interactive components):
  cols_json = {
      "column_name": {
          "type": "float64|object|int64",
          "min": value,      # for numeric
          "max": value,      # for numeric
          "values": [list]   # for categorical
      }
  }

  Data Requirements

  Pre-loaded DataFrame:
  - Polars DataFrame format (not Pandas)
  - Must match column names/types in metadata
  - Filtering applied on this DataFrame by wrapper function

  Caching Layer:
  - Redis connection (localhost:6379 in dev)
  - Used by card/figure callbacks for result caching
  - Optional but improves performance

  Data Flow:
  1. Load DataFrame once at startup
  2. Monkey-patch intercepts load_deltatable_lite() calls
  3. Apply filters from metadata
  4. Return filtered DataFrame to callbacks

  Technological Stack

  Core Framework:
  - Dash 3.2.0+ - Web framework
  - Dash Mantine Components (dmc) 2.0+ - UI components
  - Plotly - Figure rendering

  Data Processing:
  - Polars - DataFrame operations (NOT Pandas!)
  - PyArrow - Data type handling

  Backend Services:
  - Redis - Caching layer for callbacks
  - No MongoDB required (metadata pre-exported to JSON)
  - No S3/MinIO required (data pre-loaded)

  Python Dependencies:
  dash >= 3.2.0
  dash-mantine-components >= 2.0.0
  plotly
  polars
  pyarrow
  redis
  dash-iconify

  Critical Differences from Full App:
  - ❌ No FastAPI backend needed
  - ❌ No MongoDB connection needed
  - ❌ No S3/MinIO storage needed
  - ❌ No JWT authentication needed
  - ✅ Self-contained single-file application
  - ✅ All data in memory
  - ✅ Metadata from static JSON file

  Key Insights from Debugging

  1. Field Name Consistency: Store callback must use "value" (singular) not "values" - cards/figures expect this exact key
  2. Missing Components = Silent Callback Failure: If layout missing required State components (like local-store), callbacks won't register/fire
  3. Template Registration: dmc.add_figure_templates() must be called before any figures render, otherwise Plotly throws template constructor errors
  4. Metadata Format: Interactive component metadata must include nested metadata dict with dc_id, wf_id, column_name, column_type for multi-DC filtering support

  This architecture allows performance benchmarking without the overhead of the full Depictio stack (API, database, file storage), while still using the exact same rendering code
  paths.

> Explain how API calls are bypassed here ? 

⏺ I'll explain the API bypass mechanism used in the standalone Iris dashboard.

  API Bypass Architecture

  The Problem

  In the full Depictio application, components retrieve data through this chain:
  Component Callback → load_deltatable_lite() → FastAPI Endpoint → S3/MinIO → Delta Table → DataFrame

  The standalone dashboard needs to break this chain and provide data directly without:
  - FastAPI backend
  - S3/MinIO storage
  - MongoDB database
  - Network calls

  The Solution: Monkey Patching

  Location: dev/performance_analysis/standalone_iris_dashboard.py:341-413

  def install_dataframe_wrapper(df: pl.DataFrame, target_wf_id: str, target_dc_id: str):
      """
      Monkey-patch load_deltatable_lite to bypass API/S3 calls.
      
      Intercepts all data loading calls and returns pre-loaded DataFrame
      while preserving filtering logic.
      """
      # Store original function (in case we need it)
      original_load = load_deltatable_lite

      # Define wrapper that replaces the original
      def wrapper(wf_id: str, dc_id: str, **kwargs):
          # Check if this call matches our target data collection
          if wf_id == target_wf_id and dc_id == target_dc_id:
              # Extract filter metadata from kwargs
              metadata = kwargs.get("metadata", [])

              # Apply filters to pre-loaded DataFrame
              filtered_df = apply_filters(df, metadata)

              # Return in expected format
              return filtered_df
          else:
              # For any other data collection, call original
              return original_load(wf_id, dc_id, **kwargs)

      # Replace the function globally
      sys.modules['depictio.api.v1.deltatables_utils'].load_deltatable_lite = wrapper

  How It Works

  1. Function Replacement
  The wrapper replaces load_deltatable_lite() in the module namespace:

  # Before:
  load_deltatable_lite = <function that calls API/S3>

  # After install_dataframe_wrapper():
  load_deltatable_lite = <our wrapper function>

  2. Call Interception
  When a callback executes:

  # Card/Figure callback code (unchanged):
  df = load_deltatable_lite(
      wf_id="646b0f3c1e4a2d7f8e5b8c9b",
      dc_id="646b0f3c1e4a2d7f8e5b8c9c",
      metadata=[filters...]  # Interactive component values
  )

  The wrapper intercepts this call BEFORE it reaches the API.

  3. Filtering Logic Preserved
  The wrapper extracts filter metadata and applies it using the same filtering logic from the original function:

  def apply_filters(df: pl.DataFrame, metadata: list) -> pl.DataFrame:
      """Apply interactive component filters (same logic as API)."""
      for filter_item in metadata:
          column = filter_item.get("column_name")
          values = filter_item.get("value")
          component_type = filter_item.get("interactive_component_type")

          if component_type == "RangeSlider":
              # Apply range filter
              df = df.filter(
                  (pl.col(column) >= values[0]) &
                  (pl.col(column) <= values[1])
              )
          elif component_type == "MultiSelect":
              # Apply categorical filter
              if values:  # Only filter if selection not empty
                  df = df.filter(pl.col(column).is_in(values))

      return df

  4. Return Format
  The wrapper returns data in the exact same format the original function would:
  - Polars DataFrame
  - Already filtered
  - Ready for aggregation/plotting

  Visual Flow Comparison

  Full Depictio App:
  [Card Callback]
      ↓
  load_deltatable_lite(wf_id, dc_id, metadata)
      ↓
  HTTP POST /depictio/api/v1/datacollections/data
      ↓
  FastAPI endpoint validates JWT
      ↓
  Query S3/MinIO for Delta table
      ↓
  Load Delta table with filters
      ↓
  Return filtered DataFrame
      ↓
  [Card renders with data]

  Standalone Dashboard:
  [Card Callback]
      ↓
  load_deltatable_lite(wf_id, dc_id, metadata) ← INTERCEPTED HERE
      ↓
  wrapper() checks: wf_id == target? ✓
      ↓
  Apply filters to pre-loaded df
      ↓
  Return filtered DataFrame
      ↓
  [Card renders with data]

  Key Advantages

  1. Zero Code Changes to Callbacks
    - Card/figure callbacks remain completely unchanged
    - They still call load_deltatable_lite() exactly as before
    - No awareness they're running in standalone mode
  2. Preserves Filtering Logic
    - Same filter application as production
    - Ensures behavioral consistency
    - Makes performance comparison valid
  3. Single Source of Truth
    - Pre-loaded DataFrame loaded once at startup
    - All callbacks share the same data
    - No inconsistencies between components
  4. Metadata-Driven Filtering
    - Filters come from interactive-values-store
    - Same metadata structure as full app
    - Pattern-matching callbacks work identically

  Installation Point

  The wrapper is installed during app creation:

  def create_app() -> Dash:
      # ... load data ...
      df = load_iris_data()

      # ... build components ...

      # Install wrapper BEFORE registering callbacks
      install_dataframe_wrapper(
          df=df,
          target_wf_id="646b0f3c1e4a2d7f8e5b8c9b",
          target_dc_id="646b0f3c1e4a2d7f8e5b8c9c"
      )

      # Now when callbacks register, they'll use the wrapper
      register_callbacks_card_component(app)
      register_callbacks_figure_component(app)

  Limitations

  1. Single Data Collection Only
    - Wrapper hardcoded to specific wf_id/dc_id
    - Multi-DC dashboards would need enhancement
  2. No Join Support
    - Joined data collections not supported
    - Would need separate DataFrame for each DC
  3. Memory Constraints
    - Entire dataset must fit in memory
    - Not suitable for very large datasets

  This approach allows 100% code reuse from the main application while completely eliminating infrastructure dependencies. The callbacks literally don't know they're running in a
  standalone environment!

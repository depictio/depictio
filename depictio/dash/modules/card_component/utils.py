import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.colors import colors


def is_color_light(color_str: str) -> bool:
    """
    Determine if a color is light or dark using relative luminance.

    Args:
        color_str: Color string (hex like "#RRGGBB" or CSS variable)

    Returns:
        bool: True if color is light, False if dark

    Notes:
        - For CSS variables (var(...)), returns True (assumes light) as default
        - Uses W3C relative luminance formula: https://www.w3.org/TR/WCAG20/#relativeluminancedef
        - Luminance > 0.5 is considered light
    """
    # Handle CSS variables - default to light (they'll adapt with theme)
    if color_str.startswith("var("):
        return True

    # Parse hex color
    if color_str.startswith("#"):
        hex_color = color_str.lstrip("#")

        # Handle 3-digit hex (#RGB -> #RRGGBB)
        if len(hex_color) == 3:
            hex_color = "".join([c * 2 for c in hex_color])

        # Convert to RGB
        try:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0

            # Calculate relative luminance (sRGB)
            # https://www.w3.org/TR/WCAG20/#relativeluminancedef
            def linearize(c):
                if c <= 0.03928:
                    return c / 12.92
                return ((c + 0.055) / 1.055) ** 2.4

            r_lin = linearize(r)
            g_lin = linearize(g)
            b_lin = linearize(b)

            luminance = 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin

            # Luminance > 0.5 is light
            return luminance > 0.5

        except (ValueError, IndexError):
            # Invalid hex color - default to light
            return True

    # Unknown format - default to light
    return True


def get_adaptive_trend_colors(background_color: str | None) -> dict:
    """
    Get trend indicator colors that adapt to background color for optimal contrast.

    Args:
        background_color: Background color of the card (hex, CSS variable, or None for DMC theme)

    Returns:
        dict: Dictionary with 'positive', 'negative', and 'neutral' color keys

    Examples:
        >>> get_adaptive_trend_colors("#1a1a1a")  # Dark background
        {'positive': '#90EE90', 'negative': '#FFB6C1', 'neutral': '#D3D3D3'}

        >>> get_adaptive_trend_colors("#ffffff")  # Light background
        {'positive': 'green', 'negative': 'red', 'neutral': 'gray'}

        >>> get_adaptive_trend_colors(None)  # DMC auto theme - assume light
        {'positive': 'green', 'negative': 'red', 'neutral': 'gray'}
    """
    # If None or empty, assume DMC default (light) theme
    if not background_color:
        is_light = True
    else:
        is_light = is_color_light(background_color)

    if is_light:
        # Light background - use standard dark colors
        return {
            "positive": "green",
            "negative": "red",
            "neutral": "gray",
        }
    else:
        # Dark background - use bright/light colors for visibility
        return {
            "positive": "#90EE90",  # Light green
            "negative": "#FFB6C1",  # Light pink/red
            "neutral": "#D3D3D3",  # Light gray
        }


# Predefined metric themes for enhanced UX with icons and background colors
# Icons from Iconify (https://icon-sets.iconify.design/mdi/)
METRIC_THEMES = {
    "temperature": {
        "icon": "mdi:thermometer",
        "background": colors["red"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Temperature",
    },
    "salinity": {
        "icon": "mdi:water",
        "background": colors["blue"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Salinity",
    },
    "ph": {
        "icon": "mdi:flask",
        "background": colors["purple"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "pH Level",
    },
    "oxygen": {
        "icon": "mdi:air-filter",
        "background": colors["teal"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Oxygen",
    },
    "conductivity": {
        "icon": "mdi:flash",
        "background": colors["orange"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Conductivity",
    },
    "pressure": {
        "icon": "mdi:gauge",
        "background": colors["purple"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Pressure",
    },
    "humidity": {
        "icon": "mdi:water-percent",
        "background": colors["teal"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Humidity",
    },
    "depth": {
        "icon": "mdi:ruler",
        "background": colors["grey"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Depth",
    },
    "turbidity": {
        "icon": "mdi:blur",
        "background": colors["grey"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Turbidity",
    },
    "chlorophyll": {
        "icon": "mdi:leaf",
        "background": colors["green"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Chlorophyll",
    },
    # Quality control and laboratory metrics
    "quality": {
        "icon": "mdi:check-circle",
        "background": colors["green"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Quality Score",
    },
    "accuracy": {
        "icon": "mdi:target",
        "background": colors["orange"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Accuracy",
    },
    "precision": {
        "icon": "mdi:bullseye-arrow",
        "background": colors["orange"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Precision",
    },
    "purity": {
        "icon": "mdi:flask-empty",
        "background": colors["blue"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Purity",
    },
    "coverage": {
        "icon": "mdi:shield-check",
        "background": colors["teal"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Coverage",
    },
    # Statistical metrics
    "variance": {
        "icon": "mdi:chart-bell-curve",
        "background": colors["blue"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Variance",
    },
    "correlation": {
        "icon": "mdi:scatter-plot",
        "background": colors["teal"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Correlation",
    },
    "error": {
        "icon": "mdi:alert-circle",
        "background": colors["red"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Error Rate",
    },
    # Count and quantity metrics
    "count": {
        "icon": "mdi:counter",
        "background": colors["orange"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Count",
    },
    "frequency": {
        "icon": "mdi:sine-wave",
        "background": colors["purple"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Frequency",
    },
    "concentration": {
        "icon": "mdi:beaker",
        "background": colors["green"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Concentration",
    },
    # Performance metrics
    "performance": {
        "icon": "mdi:speedometer",
        "background": colors["orange"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Performance",
    },
    "throughput": {
        "icon": "mdi:flash-outline",
        "background": colors["yellow"],
        "icon_color": "#2c3e50",
        "text_color": "#2c3e50",
        "display_name": "Throughput",
    },
    "efficiency": {
        "icon": "mdi:trending-up",
        "background": colors["teal"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Efficiency",
    },
    # Sequencing/genomics metrics
    "reads": {
        "icon": "mdi:dna",
        "background": colors["purple"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Reads",
    },
    "mapping": {
        "icon": "mdi:map-marker-path",
        "background": colors["blue"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Mapping Rate",
    },
    "duplication": {
        "icon": "mdi:content-copy",
        "background": colors["red"],
        "icon_color": "#ffffff",
        "text_color": "#ffffff",
        "display_name": "Duplication",
    },
    # Generic/default theme (theme-aware for light/dark mode)
    "default": {
        "icon": "mdi:chart-line",
        "background": "var(--app-surface-color, #ffffff)",
        "icon_color": "var(--app-text-color, #000000)",
        "text_color": "var(--app-text-color, #000000)",
        "display_name": "Default",
    },
}


def detect_metric_theme(column_name: str) -> str:
    """
    Auto-detect metric theme from column name using pattern matching.

    Args:
        column_name: Name of the column to analyze

    Returns:
        Theme key from METRIC_THEMES dictionary

    Examples:
        >>> detect_metric_theme("temperature_celsius")
        'temperature'
        >>> detect_metric_theme("salinity_psu")
        'salinity'
        >>> detect_metric_theme("my_custom_column")
        'default'
    """
    if not column_name:
        return "default"

    column_lower = column_name.lower()

    # Pattern matching for common metric types
    theme_patterns = {
        # Environmental/physical metrics
        "temperature": ["temp", "temperature", "celsius", "fahrenheit", "kelvin"],
        "salinity": ["salin", "salt", "psu", "pss"],
        "ph": ["ph", "acidity", "alkalinity"],
        "oxygen": ["oxygen", "o2", "dissolved_oxygen", "do"],
        "conductivity": ["conduct", "ec", "electrical"],
        "pressure": ["press", "bar", "pascal", "psi", "atm"],
        "humidity": ["humid", "moisture", "rh"],
        "depth": ["depth", "altitude", "elevation"],
        "turbidity": ["turbid", "ntu", "clarity"],
        "chlorophyll": ["chlor", "chl", "phyto"],
        # Quality control metrics
        "quality": ["quality", "qc", "quality_score", "q_score", "qscore"],
        "accuracy": ["accuracy", "acc", "accurate"],
        "precision": ["precision", "prec", "repeatability", "reproducibility"],
        "purity": ["purity", "contam", "contamination", "pure"],
        "coverage": ["coverage", "cov", "breadth", "completeness"],
        # Statistical metrics
        "variance": ["variance", "var", "std", "stdev", "deviation"],
        "correlation": ["correlation", "corr", "pearson", "spearman", "r_value"],
        "error": ["error", "err", "fail", "failure", "reject"],
        # Count/quantity metrics
        "count": ["count", "num", "number", "n_", "total"],
        "frequency": ["frequency", "freq", "hz", "rate"],
        "concentration": ["concentration", "conc", "molarity", "intensity", "level"],
        # Performance metrics
        "performance": ["performance", "perf", "score", "metric"],
        "throughput": ["throughput", "tput", "processing_rate"],
        "efficiency": ["efficiency", "eff", "yield"],
        # Sequencing/genomics metrics
        "reads": ["reads", "read_count", "sequences", "seq"],
        "mapping": ["mapping", "mapped", "alignment", "align"],
        "duplication": ["duplication", "dup", "duplicate", "pcr_dup"],
    }

    # Check each theme's patterns
    for theme, patterns in theme_patterns.items():
        if any(pattern in column_lower for pattern in patterns):
            logger.debug(f"Auto-detected theme '{theme}' for column '{column_name}'")
            return theme

    logger.debug(f"No specific theme detected for column '{column_name}', using default")
    return "default"


def get_reference_value_from_cols_json(cols_json, column_name, aggregation):
    """
    Get reference value from cols_json statistical data instead of recomputing from full dataframe.

    Args:
        cols_json (dict): Column specifications with statistical data
        column_name (str): Name of the column
        aggregation (str): Aggregation type (count, sum, average, etc.)

    Returns:
        float or None: Reference value if available in cols_json, None otherwise
    """
    if not cols_json or column_name not in cols_json:
        logger.debug(f"Column '{column_name}' not found in cols_json")
        return None

    column_specs = cols_json[column_name].get("specs", {})
    if not column_specs:
        logger.debug(f"No specs found for column '{column_name}' in cols_json")
        return None

    # Map aggregation names to cols_json field names
    aggregation_mapping = {
        "count": "count",
        "sum": "sum",
        "average": "average",
        "median": "median",
        "min": "min",
        "max": "max",
        "nunique": "nunique",
        "unique": "unique",
        "variance": "variance",
        "std_dev": "std_dev",
        "range": "range",
        "percentile": "percentile",
    }

    # Get the corresponding field name in cols_json
    cols_json_field = aggregation_mapping.get(aggregation)
    if not cols_json_field:
        logger.debug(f"Aggregation '{aggregation}' not available in cols_json mapping")
        return None

    # Extract the value
    reference_value = column_specs.get(cols_json_field)
    if reference_value is not None:
        logger.debug(f"Found reference value for {column_name}.{aggregation}: {reference_value}")
        return reference_value
    else:
        logger.debug(f"Field '{cols_json_field}' not found in column specs for '{column_name}'")
        return None


# Mapping from custom aggregation names to pandas functions
AGGREGATION_MAPPING = {
    "count": "count",
    "sum": "sum",
    "average": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "range": "range",  # Special handling
    "variance": "var",
    "std_dev": "std",
    "skewness": "skew",
    "kurtosis": "kurt",
    "percentile": "quantile",
    "nunique": "nunique",
    # Add more mappings if necessary
}


def compute_value(data, column_name, aggregation):
    logger.debug(f"Computing value for {column_name} with {aggregation}")

    # FIXME: optimization - consider checking if data is already a pandas DataFrame
    data = data.to_pandas()

    if aggregation == "mode":
        mode_series = data[column_name].mode()
        if not mode_series.empty:
            new_value = mode_series.iloc[0]
            logger.debug(f"Computed mode: {new_value}")
            logger.debug(f"Type of mode value: {type(new_value)}")
        else:
            new_value = None
            logger.warning("No mode found; returning None")
    elif aggregation == "range":
        series = data[column_name]
        if pd.api.types.is_numeric_dtype(series):
            new_value = series.max() - series.min()
            logger.debug(f"Computed range: {new_value} (Type: {type(new_value)})")
        else:
            logger.error(
                f"Range aggregation is not supported for non-numeric column '{column_name}'."
            )
            new_value = None

    else:
        pandas_agg = AGGREGATION_MAPPING.get(aggregation)

        if not pandas_agg:
            logger.error(f"Aggregation '{aggregation}' is not supported.")
            return None
        elif pandas_agg == "range":
            # This case is already handled above
            logger.error(
                f"Aggregation '{aggregation}' requires special handling and should not reach here."
            )
            return None
        else:
            try:
                logger.debug(f"Applying aggregation function '{pandas_agg}'")
                # logger.info(f"Column name: {column_name}")
                # logger.info(f"Data: {data}")
                # logger.info(f"Data cols {data.columns}")
                # logger.info(f"Data type: {data[column_name].dtype}")
                # logger.info(f"Data: {data[column_name]}")
                new_value = data[column_name].agg(pandas_agg)
                logger.debug(
                    f"Computed {aggregation} ({pandas_agg}): {new_value} (Type: {type(new_value)})"
                )
            except AttributeError as e:
                logger.error(f"Aggregation function '{pandas_agg}' failed: {e}")
                new_value = None

        if isinstance(new_value, np.float64):
            new_value = round(new_value, 4)
            logger.debug(f"New value rounded: {new_value}")

    return new_value


def build_card_frame(index, children=None, show_border=False):
    if not children:
        return dmc.Paper(
            children=[
                dmc.LoadingOverlay(
                    id={"type": "card-loading-overlay", "index": index},
                    visible=False,  # Always hidden for baseline performance testing
                    overlayProps={"radius": "sm", "blur": 2},
                    loaderProps={"type": "dots", "size": "lg"},
                    zIndex=10,
                    style={"display": "none"},  # Force hide to eliminate overlay overhead
                ),
                dmc.Center(
                    dmc.Text(
                        "Configure your card using the edit menu",
                        size="sm",
                        c="gray",
                        fs="italic",
                        ta="center",
                    ),
                    id={
                        "type": "card-body",
                        "index": index,
                    },
                    style={
                        "minHeight": "150px",
                        "height": "100%",
                        "minWidth": "150px",
                    },
                ),
            ],
            id={
                "type": "card-component",
                "index": index,
            },
            pos="relative",
            withBorder=show_border,
            radius="sm",
            p="md",
            style={
                "width": "100%",
                "height": "100%",
                "margin": "0",
            },
        )
    else:
        return dmc.Paper(
            children=[
                dmc.LoadingOverlay(
                    id={"type": "card-loading-overlay", "index": index},
                    visible=False,  # Always hidden for baseline performance testing
                    overlayProps={"radius": "sm", "blur": 2},
                    loaderProps={"type": "dots", "size": "lg"},
                    zIndex=10,
                    style={"display": "none"},  # Force hide to eliminate overlay overhead
                ),
                dmc.Stack(
                    children=children,
                    id={
                        "type": "card-body",
                        "index": index,
                    },
                    gap="xs",
                    style={
                        "height": "100%",
                    },
                ),
            ],
            id={
                "type": "card-component",
                "index": index,
            },
            pos="relative",
            withBorder=show_border,
            radius="sm",
            p="xs",
            style={
                "width": "100%",
                "height": "100%",
                "margin": "0",
            },
        )


def build_card(**kwargs):
    """
    Build card component structure with pattern-matching callback architecture.

    This function creates the card component UI structure but does NOT compute values.
    Value computation happens asynchronously in render_card_value_background callback.

    Pattern-matching IDs enable independent rendering of each card instance:
    - {"type": "card-trigger", "index": component_id} - Initiates rendering
    - {"type": "card-value", "index": component_id} - Updated by callbacks
    - {"type": "card-comparison", "index": component_id} - Shows filter comparison
    - {"type": "card-metadata", "index": component_id} - Stores reference data
    """
    # DUPLICATION TRACKING: Log card component builds
    logger.info(
        f"🔍 BUILD CARD CALLED - Index: {kwargs.get('index', 'UNKNOWN')}, Stepper: {kwargs.get('stepper', False)}"
    )

    index = kwargs.get("index")
    title = kwargs.get("title", "Default Title")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    aggregation = kwargs.get("aggregation")
    v = kwargs.get("value")  # Legacy support - may still be provided
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    color = kwargs.get("color", None)
    # SECURITY: access_token removed - no longer stored in component metadata
    parent_index = kwargs.get("parent_index", None)
    metric_theme = kwargs.get("metric_theme", None)

    # DASHBOARD OPTIMIZATION: Extract init_data for API call elimination
    init_data = kwargs.get("init_data", None)
    logger.debug(f"Init data provided: {init_data is not None}")

    # REFACTORING: cols_json and dc_config no longer stored in component metadata
    # Callbacks access these directly from dashboard-init-data store via State input
    # This eliminates per-component data duplication and reduces payload size
    if init_data:
        logger.info(
            f"📡 CARD OPTIMIZATION: init_data available with {len(init_data.get('column_specs', {}))} column_specs"
        )
    else:
        logger.debug("⚠️  init_data not available (edit mode or stepper mode)")

    # New individual style parameters
    # Convert empty strings to None for DMC theme compliance
    background_color = kwargs.get("background_color") or None
    title_color = kwargs.get("title_color") or None
    icon_name = kwargs.get("icon_name", None)
    icon_color = kwargs.get("icon_color") or None
    title_font_size = kwargs.get("title_font_size", "md")
    value_font_size = kwargs.get("value_font_size", "xl")

    # Backward compatibility: Auto-detect theme if not provided and no individual styles set
    # Only auto-detect if we don't have explicit style parameters
    if not metric_theme and not any([background_color, title_color, icon_name]):
        if column_name:
            metric_theme = detect_metric_theme(column_name)
        else:
            metric_theme = "default"

    # Extract styles from theme if metric_theme is provided (backward compatibility)
    # Otherwise use individual parameters with DMC theme-aware defaults
    if metric_theme and metric_theme != "default":
        theme_config = METRIC_THEMES.get(metric_theme, METRIC_THEMES["default"])
        # Use individual parameters if provided, otherwise fall back to theme
        background_color = background_color or theme_config["background"]
        title_color = title_color or theme_config["text_color"]
        icon_name = icon_name or theme_config["icon"]
        icon_color = icon_color or theme_config["icon_color"]
        logger.debug(f"Using metric theme '{metric_theme}' for column '{column_name}'")
    else:
        # No theme - use individual parameters with DMC defaults (None = auto-theme)
        # DMC compliance: None values let DMC theme system handle colors automatically
        background_color = background_color  # None or user-specified
        title_color = title_color  # None or user-specified
        icon_name = icon_name or "mdi:chart-line"
        icon_color = icon_color  # None or user-specified
        logger.debug(f"Using DMC theme-compliant styling for column '{column_name}'")

    if stepper:
        # Defensive check: only append -tmp if not already present
        if not str(index).endswith("-tmp"):
            index = f"{index}-tmp"

    # SIMPLE SKELETON APPROACH: Build actual component with skeleton placeholder
    # No progressive loading - component renders with skeleton, callback populates it
    # Removed early return that was showing separate placeholder spinner

    # PATTERN-MATCHING ARCHITECTURE: All data loading and value computation moved to callbacks
    # This function only creates the UI structure - values populate asynchronously via:
    # - render_card_value_background() for initial values
    # - patch_card_with_filters() for filter updates
    # - update_card_theme() for theme changes

    logger.debug(f"Creating card structure for index: {index}")

    # Metadata management
    if stepper:
        store_index = index
        data_index = index.replace("-tmp", "") if index else "unknown"
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"
        data_index = store_index

    # Component metadata store (for dashboard save/restore)
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(store_index),
        },
        data={
            "index": str(data_index),
            "component_type": "card",
            "title": title,
            "wf_id": wf_id,
            "dc_id": dc_id,
            # REFACTORING: dc_config removed - available via dashboard-init-data
            "aggregation": aggregation,
            "column_type": column_type,
            "column_name": column_name,
            "value": v,  # Legacy support - may be None for new pattern-matching cards
            "parent_index": parent_index,
            "metric_theme": metric_theme,  # Deprecated, kept for backward compatibility
            # New individual style fields
            "background_color": background_color,
            "title_color": title_color,
            "icon_name": icon_name,
            "icon_color": icon_color,
            "title_font_size": title_font_size,
            "value_font_size": value_font_size,
        },
    )

    # PATTERN-MATCHING: Trigger store - initiates async rendering
    # This store triggers the render_card_value_background callback
    #
    # NOTE: Progressive loading components create their own empty trigger Store
    # via progressive_loading_component.py:136-139. This trigger Store is used
    # for non-progressive components (stepper mode, direct builds).
    trigger_store = dcc.Store(
        id={
            "type": "card-trigger",
            "index": str(index),
        },
        data={
            "wf_id": wf_id,
            "dc_id": dc_id,
            "column_name": column_name,
            "column_type": column_type,
            "aggregation": aggregation,
            "title": title,
            "color": color,
            # SECURITY: access_token removed - accessed from local-store in callbacks
            "stepper": stepper,
            "metric_theme": metric_theme,  # Deprecated, kept for backward compatibility
            # New individual style fields
            "background_color": background_color,
            "title_color": title_color,
            "icon_name": icon_name,
            "icon_color": icon_color,
            "title_font_size": title_font_size,
            "value_font_size": value_font_size,
            # REFACTORING: cols_json and dc_config removed from component stores
            # Callbacks access dashboard-init-data store directly via State input
        },
    )

    # PATTERN-MATCHING: Metadata store - for callbacks (reference values, etc.)
    metadata_store = dcc.Store(
        id={
            "type": "card-metadata",
            "index": str(index),
        },
        data={},  # Populated by patch callback with has_been_patched flag
    )

    # PATTERN-MATCHING: Initial metadata store - for render callback
    # CRITICAL: Separate store to avoid Dash background callback bug with allow_duplicate=True
    # This store is written ONLY by render_card_value_background (contains reference_value)
    # Patch callback reads from this store to get reference_value
    metadata_initial_store = dcc.Store(
        id={
            "type": "card-metadata-initial",
            "index": str(index),
        },
        data={},  # Populated by render callback with reference_value
    )

    # Create card title
    if aggregation and hasattr(aggregation, "title"):
        agg_display = aggregation.title()
    else:
        agg_display = str(aggregation).title() if aggregation else "Unknown"

    card_title = title if title else f"{agg_display} of {column_name}"

    # PATTERN-MATCHING ARCHITECTURE: Create card with placeholder content
    # Actual values will be populated by render_card_value_background callback
    # Comparison text will be added by patch_card_with_filters callback

    # Use legacy value if provided (for backward compatibility), otherwise show loading skeleton
    # Simple skeleton loader that will be replaced by callback
    if v is not None:
        display_value = str(v)
    else:
        display_value = html.Span(
            dmc.Loader(type="dots", size="lg"), style={"textAlign": "center", "padding": "10px"}
        )

    # Add icon overlay (always show icon now, not just for themed cards)
    # Build icon style (no color - DashIconify uses direct color prop)
    icon_style = {
        "opacity": "0.3",
        "position": "absolute",
        "right": "10px",
        "top": "10px",
    }

    # Build DashIconify kwargs conditionally - apply color via CSS style to prevent browser freeze
    dashiconify_kwargs = {
        "icon": icon_name,
        "width": 40,
        "style": icon_style.copy(),  # Copy to avoid mutating the original dict
    }
    if icon_color:
        dashiconify_kwargs["style"]["color"] = icon_color

    icon_overlay_component = [
        dmc.Group(
            [
                DashIconify(**dashiconify_kwargs),
            ],
            style={"position": "relative"},
        )
    ]

    # Build text components with conditional color props (DMC compliance)
    # Only set 'c' prop if title_color is specified, otherwise let DMC theme handle it
    title_text_kwargs = {
        "children": card_title,
        "size": title_font_size,
        "fw": "bold",
        "style": {"margin": "0", "marginLeft": "-2px"},
    }
    if title_color:
        title_text_kwargs["c"] = title_color

    value_text_style = {"margin": "0", "marginLeft": "-2px"}
    if title_color:
        value_text_style["color"] = title_color

    card_content = [
        *icon_overlay_component,  # Unpack the list here
        dmc.Text(**title_text_kwargs),
        dmc.Text(
            display_value,
            size=value_font_size,
            fw="bold",
            id={
                "type": "card-value",
                "index": str(index),
            },
            style=value_text_style,
        ),
        # PATTERN-MATCHING: Comparison container - populated by patching callback
        dmc.Group(
            [],
            id={
                "type": "card-comparison",
                "index": str(index),
            },
            gap="xs",
            align="center",
            justify="flex-start",
            style={"margin": "0", "marginLeft": "-2px"},
        ),
        # Legacy metadata store (for dashboard save/restore)
        store_component,
        # Pattern-matching stores (for async rendering)
        trigger_store,
        metadata_store,
        metadata_initial_store,  # Separate store for render callback (avoids allow_duplicate bug)
    ]
    # Removed the conditional insert as icon_overlay_component is now unpacked directly

    # Create the modern card body using DMC Card component
    # When in stepper mode without frame, use minimal styling to avoid double box
    # Determine card styling based on whether it's a custom styled card
    # DMC compliance: Only set bg if background_color is specified (not None)
    has_custom_styling = background_color is not None
    card_radius = "8px" if has_custom_styling else "sm"
    card_padding = "1rem" if has_custom_styling else "xs"

    # Build CardSection kwargs conditionally (DMC compliance)
    card_section_kwargs = {
        "children": card_content,
        "bdrs": card_radius,
        "p": card_padding,
        "style": {
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "center",
        },
    }
    # Only set bg prop if background_color is specified (DMC theme compliance)
    if background_color:
        card_section_kwargs["bg"] = background_color

    # Build the card component with standard styling
    card_style = {
        "boxSizing": "content-box",
        "height": "100%",
        "minHeight": "120px",
    }

    new_card_body = dmc.Card(
        children=[dmc.CardSection(**card_section_kwargs)],
        withBorder=True,
        shadow="sm",
        style=card_style,
        id={
            "type": "card",
            "index": str(index),
        },
    )

    if not build_frame:
        # Return single component (not wrapped in list) for consistency
        # The callback output 'children' can accept single component or list
        return new_card_body
    else:
        # Build the card frame with LoadingOverlay for both dashboard and stepper modes
        card_component = build_card_frame(index=index, children=new_card_body, show_border=stepper)
        return card_component


# List of all the possible aggregation methods for each data type
# TODO: reference in the documentation
agg_functions = {
    "int64": {
        "title": "Integer",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": "range",  # Special handling in compute_value
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
        },
    },
    "float64": {
        "title": "Floating Point",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "average": {
                "pandas": "mean",
                "numpy": "mean",
                "description": "Mean of non-NA values",
            },
            "median": {
                "pandas": "median",
                "numpy": "median",
                "description": "Arithmetic median of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
            "range": {
                "pandas": lambda x: x.max() - x.min(),
                "numpy": "ptp",
                "description": "Range of non-NA values",
            },
            "variance": {
                "pandas": "var",
                "numpy": "var",
                "description": "Variance of non-NA values",
            },
            "std_dev": {
                "pandas": "std",
                "numpy": "std",
                "description": "Standard Deviation of non-NA values",
            },
            "percentile": {
                "pandas": "quantile",
                "numpy": "percentile",
                "description": "Percentiles of non-NA values",
            },
            "skewness": {
                "pandas": "skew",
                "numpy": None,
                "description": "Skewness of non-NA values",
            },
            "kurtosis": {
                "pandas": "kurt",
                "numpy": None,
                "description": "Kurtosis of non-NA values",
            },
            # "cumulative_sum": {
            #     "pandas": "cumsum",
            #     "numpy": "cumsum",
            #     "description": "Cumulative sum of non-NA values",
            # },
        },
    },
    "bool": {
        "title": "Boolean",
        "description": "Boolean values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "datetime": {
        "title": "Datetime",
        "description": "Date and time values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "timedelta": {
        "title": "Timedelta",
        "description": "Differences between two datetimes",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "sum": {
                "pandas": "sum",
                "numpy": "sum",
                "description": "Sum of non-NA values",
            },
            "min": {
                "pandas": "min",
                "numpy": "min",
                "description": "Minimum of non-NA values",
            },
            "max": {
                "pandas": "max",
                "numpy": "max",
                "description": "Maximum of non-NA values",
            },
        },
    },
    "category": {
        "title": "Category",
        "description": "Finite list of text values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
        },
    },
    "object": {
        "title": "Object",
        "description": "Text or mixed numeric or non-numeric values",
        "card_methods": {
            "count": {
                "pandas": "count",
                "numpy": "count_nonzero",
                "description": "Counts the number of non-NA cells",
            },
            "mode": {
                "pandas": "mode",
                "numpy": None,
                "description": "Most common value",
            },
            "nunique": {
                "pandas": "nunique",
                "numpy": None,
                "description": "Number of distinct elements",
            },
        },
    },
}


# Async wrapper for background callbacks - now calls sync version
async def build_card_async(**kwargs):
    """
    Async wrapper for build_card function - async functionality disabled, calls sync version.
    """
    logger.info(
        f"🔄 ASYNC CARD: Building card component (using sync) - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_card function
    result = build_card(**kwargs)

    logger.info(
        f"✅ ASYNC CARD: Card component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result

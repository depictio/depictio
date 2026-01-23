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


def compute_value(data, column_name, aggregation, cols_json=None, has_filters=False):
    """
    Compute aggregated value for a column.

    Args:
        data: Polars or Pandas DataFrame
        column_name: Column to aggregate
        aggregation: Aggregation type (sum, average, etc.)
        cols_json: Optional column metadata with pre-computed statistics
        has_filters: Whether filters are active (skips pre-computed stats if True)

    Returns:
        Aggregated value
    """
    logger.debug(f"Computing value for {column_name} with {aggregation} (filters={has_filters})")

    # OPTIMIZATION 1: Try pre-computed statistics first (only when no filters active)
    if not has_filters and cols_json:
        reference_value = get_reference_value_from_cols_json(cols_json, column_name, aggregation)
        if reference_value is not None:
            return reference_value

    # OPTIMIZATION 2: Use Polars native operations (avoid pandas conversion)
    # Check if data is already Polars DataFrame
    import polars as pl

    is_polars = isinstance(data, pl.DataFrame) or isinstance(data, pl.LazyFrame)

    # Convert to pandas only if necessary (for mode aggregation)
    if aggregation == "mode":
        if is_polars:
            data_pd = data.to_pandas()
        else:
            data_pd = data
        mode_series = data_pd[column_name].mode()
        if not mode_series.empty:
            new_value = mode_series.iloc[0]
            logger.debug(f"Computed mode: {new_value}")
            logger.debug(f"Type of mode value: {type(new_value)}")
        else:
            new_value = None
            logger.warning("No mode found; returning None")
    elif aggregation == "range":
        if is_polars:
            # Polars native range computation
            col = data[column_name]
            new_value = col.max() - col.min()
            logger.debug(f"Computed range (Polars): {new_value}")
        else:
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
        # Map to appropriate function
        if is_polars:
            # Polars aggregation mapping
            polars_agg_map = {
                "count": "count",
                "sum": "sum",
                "average": "mean",
                "median": "median",
                "min": "min",
                "max": "max",
                "variance": "var",
                "std_dev": "std",
                "nunique": "n_unique",
            }
            polars_agg = polars_agg_map.get(aggregation)

            if not polars_agg:
                logger.error(f"Aggregation '{aggregation}' is not supported for Polars.")
                return None

            try:
                logger.debug(f"Applying Polars aggregation '{polars_agg}'")
                col = data[column_name]

                # Use Polars expression API
                if polars_agg == "count":
                    new_value = col.len()
                elif polars_agg == "sum":
                    new_value = col.sum()
                elif polars_agg == "mean":
                    new_value = col.mean()
                elif polars_agg == "median":
                    new_value = col.median()
                elif polars_agg == "min":
                    new_value = col.min()
                elif polars_agg == "max":
                    new_value = col.max()
                elif polars_agg == "var":
                    new_value = col.var()
                elif polars_agg == "std":
                    new_value = col.std()
                elif polars_agg == "n_unique":
                    new_value = col.n_unique()
                else:
                    logger.error(f"Unhandled Polars aggregation: {polars_agg}")
                    new_value = None

                logger.debug(
                    f"Computed {aggregation} ({polars_agg}) [Polars]: {new_value} (Type: {type(new_value)})"
                )
            except Exception as e:
                logger.error(f"Polars aggregation '{polars_agg}' failed: {e}")
                new_value = None
        else:
            # Pandas aggregation (fallback)
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


# ============================================================================
# BUILD_CARD HELPER FUNCTIONS
# ============================================================================


def _resolve_card_styles(
    column_name: str | None,
    metric_theme: str | None,
    background_color: str | None,
    title_color: str | None,
    icon_name: str | None,
    icon_color: str | None,
) -> dict:
    """
    Resolve card styling from theme and individual parameters.

    Args:
        column_name: Column name for auto-theme detection
        metric_theme: Explicit metric theme name
        background_color: Explicit background color
        title_color: Explicit title color
        icon_name: Explicit icon name
        icon_color: Explicit icon color

    Returns:
        Dictionary with resolved style values
    """
    # Auto-detect theme if not provided and no individual styles set
    if not metric_theme and not any([background_color, title_color, icon_name]):
        if column_name:
            metric_theme = detect_metric_theme(column_name)
        else:
            metric_theme = "default"

    # Extract styles from theme if metric_theme is provided
    if metric_theme and metric_theme != "default":
        theme_config = METRIC_THEMES.get(metric_theme, METRIC_THEMES["default"])
        resolved_bg = background_color or theme_config["background"]
        resolved_title = title_color or theme_config["text_color"]
        resolved_icon = icon_name or theme_config["icon"]
        resolved_icon_color = icon_color or theme_config["icon_color"]
        logger.debug(f"Using metric theme '{metric_theme}' for column '{column_name}'")
    else:
        # No theme - use individual parameters with DMC defaults
        resolved_bg = background_color
        resolved_title = title_color
        resolved_icon = icon_name or "mdi:chart-line"
        resolved_icon_color = icon_color
        logger.debug(f"Using DMC theme-compliant styling for column '{column_name}'")

    return {
        "background_color": resolved_bg,
        "title_color": resolved_title,
        "icon_name": resolved_icon,
        "icon_color": resolved_icon_color,
        "metric_theme": metric_theme,
    }


def _create_card_stores(
    index: str,
    store_index: str,
    data_index: str,
    wf_id: str | None,
    dc_id: str | None,
    title: str,
    column_name: str | None,
    column_type: str | None,
    aggregation: str | None,
    value: any,
    parent_index: str | None,
    styles: dict,
    color: str | None,
    stepper: bool,
    title_font_size: str,
    value_font_size: str,
    project_id: str | None = None,
) -> tuple:
    """
    Create the store components for card metadata and triggering.

    Args:
        project_id: Project ID for cross-DC link resolution

    Returns:
        Tuple of (store_component, trigger_store, metadata_store, metadata_initial_store)
    """
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
            "project_id": project_id,  # For cross-DC link resolution
            "aggregation": aggregation,
            "column_type": column_type,
            "column_name": column_name,
            "value": value,
            "parent_index": parent_index,
            "metric_theme": styles["metric_theme"],
            "background_color": styles["background_color"],
            "title_color": styles["title_color"],
            "icon_name": styles["icon_name"],
            "icon_color": styles["icon_color"],
            "title_font_size": title_font_size,
            "value_font_size": value_font_size,
        },
    )

    # Trigger store - initiates async rendering
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
            "stepper": stepper,
            "metric_theme": styles["metric_theme"],
            "background_color": styles["background_color"],
            "title_color": styles["title_color"],
            "icon_name": styles["icon_name"],
            "icon_color": styles["icon_color"],
            "title_font_size": title_font_size,
            "value_font_size": value_font_size,
        },
    )

    # Metadata store - for callbacks (reference values, etc.)
    metadata_store = dcc.Store(
        id={
            "type": "card-metadata",
            "index": str(index),
        },
        data={},
    )

    # Initial metadata store - for render callback
    metadata_initial_store = dcc.Store(
        id={
            "type": "card-metadata-initial",
            "index": str(index),
        },
        data={},
    )

    return store_component, trigger_store, metadata_store, metadata_initial_store


def _create_icon_overlay(icon_name: str, icon_color: str | None) -> list:
    """
    Create the icon overlay component for the card.

    Args:
        icon_name: Icon name from Iconify
        icon_color: Optional icon color

    Returns:
        List containing the icon overlay group
    """
    icon_style = {
        "opacity": "0.3",
        "position": "absolute",
        "right": "10px",
        "top": "10px",
    }

    dashiconify_kwargs = {
        "icon": icon_name,
        "width": 40,
        "style": icon_style.copy(),
    }
    if icon_color:
        dashiconify_kwargs["style"]["color"] = icon_color

    return [
        dmc.Group(
            [DashIconify(**dashiconify_kwargs)],
            style={"position": "relative"},
        )
    ]


def _create_card_content(
    index: str,
    card_title: str,
    display_value: any,
    styles: dict,
    title_font_size: str,
    value_font_size: str,
    stores: tuple,
) -> list:
    """
    Create the card content including title, value, and comparison containers.

    Args:
        index: Component index
        card_title: Display title for the card
        display_value: Value to display (or loading skeleton)
        styles: Resolved style dictionary
        title_font_size: Font size for title
        value_font_size: Font size for value
        stores: Tuple of store components

    Returns:
        List of card content components
    """
    store_component, trigger_store, metadata_store, metadata_initial_store = stores

    # Create icon overlay
    icon_overlay = _create_icon_overlay(styles["icon_name"], styles["icon_color"])

    # Build title text kwargs
    title_text_kwargs = {
        "children": card_title,
        "size": title_font_size,
        "fw": "bold",
        "style": {"margin": "0", "marginLeft": "-2px"},
    }
    if styles["title_color"]:
        title_text_kwargs["c"] = styles["title_color"]

    # Build value text style
    value_text_style = {"margin": "0", "marginLeft": "-2px"}
    if styles["title_color"]:
        value_text_style["color"] = styles["title_color"]

    return [
        *icon_overlay,
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
        # Comparison container - populated by patching callback
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
        store_component,
        trigger_store,
        metadata_store,
        metadata_initial_store,
    ]


def _build_card_component(
    index: str,
    card_content: list,
    background_color: str | None,
) -> dmc.Card:
    """
    Build the final DMC Card component with proper styling.

    Args:
        index: Component index
        card_content: List of card content components
        background_color: Background color (None for DMC theme)

    Returns:
        DMC Card component
    """
    has_custom_styling = background_color is not None
    card_radius = "8px" if has_custom_styling else "sm"
    card_padding = "1rem" if has_custom_styling else "xs"

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
    if background_color:
        card_section_kwargs["bg"] = background_color

    card_style = {
        "boxSizing": "content-box",
        "height": "100%",
        "minHeight": "120px",
    }

    return dmc.Card(
        children=[dmc.CardSection(**card_section_kwargs)],
        withBorder=True,
        shadow="sm",
        style=card_style,
        id={
            "type": "card",
            "index": str(index),
        },
    )


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
    logger.info(
        f"BUILD CARD CALLED - Index: {kwargs.get('index', 'UNKNOWN')}, "
        f"Stepper: {kwargs.get('stepper', False)}"
    )

    # Extract parameters
    index = kwargs.get("index")
    title = kwargs.get("title", "Default Title")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    aggregation = kwargs.get("aggregation")
    v = kwargs.get("value")
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    color = kwargs.get("color", None)
    parent_index = kwargs.get("parent_index", None)
    metric_theme = kwargs.get("metric_theme", None)
    init_data = kwargs.get("init_data", None)

    # Style parameters (convert empty strings to None for DMC compliance)
    background_color = kwargs.get("background_color") or None
    title_color = kwargs.get("title_color") or None
    icon_name = kwargs.get("icon_name", None)
    icon_color = kwargs.get("icon_color") or None
    title_font_size = kwargs.get("title_font_size", "md")
    value_font_size = kwargs.get("value_font_size", "xl")

    if init_data:
        logger.info(
            f"CARD OPTIMIZATION: init_data available with "
            f"{len(init_data.get('column_specs', {}))} column_specs"
        )

    # Resolve styles from theme and individual parameters
    styles = _resolve_card_styles(
        column_name, metric_theme, background_color, title_color, icon_name, icon_color
    )

    # Handle stepper mode index
    if stepper and not str(index).endswith("-tmp"):
        index = f"{index}-tmp"

    logger.debug(f"Creating card structure for index: {index}")

    # Determine store indices
    if stepper:
        store_index = index
        data_index = index.replace("-tmp", "") if index else "unknown"
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"
        data_index = store_index

    # Create store components (includes project_id for cross-DC link resolution)
    stores = _create_card_stores(
        index=index,
        store_index=store_index,
        data_index=data_index,
        wf_id=wf_id,
        dc_id=dc_id,
        title=title,
        column_name=column_name,
        column_type=column_type,
        aggregation=aggregation,
        value=v,
        parent_index=parent_index,
        styles=styles,
        color=color,
        stepper=stepper,
        title_font_size=title_font_size,
        value_font_size=value_font_size,
        project_id=kwargs.get("project_id"),
    )

    # Create card title
    if aggregation and hasattr(aggregation, "title"):
        agg_display = aggregation.title()
    else:
        agg_display = str(aggregation).title() if aggregation else "Unknown"
    card_title = title if title else f"{agg_display} of {column_name}"

    # Create display value (legacy value or loading skeleton)
    if v is not None:
        display_value = str(v)
    else:
        display_value = html.Span(
            dmc.Loader(type="dots", size="lg"),
            style={"textAlign": "center", "padding": "10px"},
        )

    # Create card content
    card_content = _create_card_content(
        index=index,
        card_title=card_title,
        display_value=display_value,
        styles=styles,
        title_font_size=title_font_size,
        value_font_size=value_font_size,
        stores=stores,
    )

    # Build the card component
    new_card_body = _build_card_component(
        index=index,
        card_content=card_content,
        background_color=styles["background_color"],
    )

    if not build_frame:
        return new_card_body
    else:
        return build_card_frame(index=index, children=new_card_body, show_border=stepper)


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

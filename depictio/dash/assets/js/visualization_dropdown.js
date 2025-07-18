// Visualization dropdown renderOption function
var dmcfuncs = window.dashMantineFunctions = window.dashMantineFunctions || {};
var dmc = window.dash_mantine_components;
var iconify = window.dash_iconify;

dmcfuncs.renderVisualizationOption = function ({ option, checked }) {
  // Check if this is a group header, separator, or special option
  const isGroupHeader = option.value.startsWith("__group__");
  const isSeparator = option.value.startsWith("__separator__") || option.label === "";
  const isInfo = option.value.startsWith("__info__");

  // For group headers, separators, or info items, don't show icons
  if (isGroupHeader || isSeparator || isInfo) {
    return React.createElement(
      "div",
      {
        style: {
          fontSize: "14px",
          fontWeight: isGroupHeader ? "bold" : "normal",
          color: isGroupHeader ? "#495057" : "#868e96",
          padding: isSeparator ? "2px 0" : "4px 0"
        }
      },
      option.label
    );
  }

  // Icon mapping for visualization types (only for actual visualizations)
  const icons = {
    scatter: React.createElement(iconify.DashIconify, { icon: "mdi:chart-scatter-plot", width: 16 }),
    line: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line", width: 16 }),
    bar: React.createElement(iconify.DashIconify, { icon: "mdi:chart-bar", width: 16 }),
    box: React.createElement(iconify.DashIconify, { icon: "mdi:chart-box-outline", width: 16 }),
    histogram: React.createElement(iconify.DashIconify, { icon: "mdi:chart-histogram", width: 16 }),
    violin: React.createElement(iconify.DashIconify, { icon: "mdi:violin", width: 16 }),
    pie: React.createElement(iconify.DashIconify, { icon: "mdi:chart-pie", width: 16 }),
    sunburst: React.createElement(iconify.DashIconify, { icon: "mdi:chart-donut", width: 16 }),
    treemap: React.createElement(iconify.DashIconify, { icon: "mdi:view-grid", width: 16 }),
    area: React.createElement(iconify.DashIconify, { icon: "mdi:chart-areaspline", width: 16 }),
    density_contour: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line-variant", width: 16 }),
    density_heatmap: React.createElement(iconify.DashIconify, { icon: "mdi:grid", width: 16 }),
    funnel: React.createElement(iconify.DashIconify, { icon: "mdi:filter-variant", width: 16 }),
    strip: React.createElement(iconify.DashIconify, { icon: "mdi:chart-scatter-plot-hexbin", width: 16 }),
    parallel_coordinates: React.createElement(iconify.DashIconify, { icon: "mdi:chart-multiline", width: 16 }),
    parallel_categories: React.createElement(iconify.DashIconify, { icon: "mdi:chart-sankey-variant", width: 16 }),
    imshow: React.createElement(iconify.DashIconify, { icon: "mdi:image-outline", width: 16 }),
    ecdf: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line-stacked", width: 16 }),
    icicle: React.createElement(iconify.DashIconify, { icon: "mdi:chart-tree", width: 16 }),
    timeline: React.createElement(iconify.DashIconify, { icon: "mdi:chart-timeline", width: 16 }),

    // Additional visualization types
    bar_polar: React.createElement(iconify.DashIconify, { icon: "mdi:chart-bar", width: 16 }),
    choropleth: React.createElement(iconify.DashIconify, { icon: "mdi:map", width: 16 }),
    choropleth_map: React.createElement(iconify.DashIconify, { icon: "mdi:map-outline", width: 16 }),
    choropleth_mapbox: React.createElement(iconify.DashIconify, { icon: "mdi:map", width: 16 }),
    density_map: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker-radius", width: 16 }),
    density_mapbox: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker-radius", width: 16 }),
    funnel_area: React.createElement(iconify.DashIconify, { icon: "mdi:filter-variant", width: 16 }),
    line_3d: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line", width: 16 }),
    line_geo: React.createElement(iconify.DashIconify, { icon: "mdi:earth", width: 16 }),
    line_map: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker-path", width: 16 }),
    line_mapbox: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker-path", width: 16 }),
    line_polar: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line", width: 16 }),
    line_ternary: React.createElement(iconify.DashIconify, { icon: "mdi:chart-line", width: 16 }),
    scatter_3d: React.createElement(iconify.DashIconify, { icon: "mdi:chart-scatter-plot", width: 16 }),
    scatter_geo: React.createElement(iconify.DashIconify, { icon: "mdi:earth", width: 16 }),
    scatter_map: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker", width: 16 }),
    scatter_mapbox: React.createElement(iconify.DashIconify, { icon: "mdi:map-marker", width: 16 }),
    scatter_matrix: React.createElement(iconify.DashIconify, { icon: "mdi:matrix", width: 16 }),
    scatter_polar: React.createElement(iconify.DashIconify, { icon: "mdi:chart-scatter-plot", width: 16 }),
    scatter_ternary: React.createElement(iconify.DashIconify, { icon: "mdi:chart-scatter-plot", width: 16 }),

    // Clustering visualizations
    umap: React.createElement(iconify.DashIconify, { icon: "mdi:scatter-plot", width: 16 }),
  };

  // Default icon for unknown types
  const defaultIcon = React.createElement(iconify.DashIconify, { icon: "mdi:chart-line", width: 16 });

  // Get the icon for this option, or use default
  const icon = icons[option.value] || defaultIcon;

  // Checked icon
  const checkedIcon = React.createElement(iconify.DashIconify, {
    icon: "mdi:check",
    width: 16,
  });

  return React.createElement(
    dmc.Group,
    { flex: "1", gap: "xs", style: { fontSize: "14px" } },
    icon,
    option.label,
    checked ? checkedIcon : null
  );
};

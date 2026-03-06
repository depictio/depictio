
/**
 * Leaflet map JavaScript functions for dash-leaflet GeoJSON styling and interaction.
 * Used via dash_extensions.javascript.Namespace references.
 */
window.dashExtensions = Object.assign({}, window.dashExtensions, {
    map: {
        /**
         * Per-feature style function. Reads color from hideout.color_map
         * based on the feature property specified by hideout.color_prop.
         */
        styleFunction: function(feature, context) {
            var props = feature.properties || {};
            var colorProp = context.hideout.color_prop || "land_cover";
            var colorMap = context.hideout.color_map || {};
            var defaultColor = context.hideout.default_color || "#888888";
            var value = props[colorProp] || "";
            var fillColor = colorMap[value] || defaultColor;
            var fillOpacity = context.hideout.fill_opacity !== undefined ? context.hideout.fill_opacity : 0.6;
            return {
                fillColor: fillColor,
                color: fillColor,
                weight: 0.5,
                opacity: 0.8,
                fillOpacity: fillOpacity
            };
        },

        /**
         * Hover highlight style - increases weight and opacity on mouseover.
         */
        hoverStyle: function(feature, context) {
            return {
                weight: 2,
                opacity: 1,
                fillOpacity: 0.85
            };
        },

        /**
         * Bind tooltips to each feature showing land_cover, impact_index, and city.
         */
        onEachFeature: function(feature, layer) {
            var props = feature.properties || {};
            var parts = [];
            if (props.land_cover) {
                parts.push("<b>Land Cover:</b> " + props.land_cover);
            }
            if (props.impact_index !== undefined && props.impact_index !== null) {
                parts.push("<b>Impact Index:</b> " + parseFloat(props.impact_index).toFixed(2));
            }
            if (props.city) {
                parts.push("<b>City:</b> " + props.city);
            }
            if (parts.length > 0) {
                layer.bindTooltip(parts.join("<br>"), {
                    sticky: true,
                    direction: "top",
                    opacity: 0.9
                });
            }
        },

        /**
         * Render scatter overlay points as CircleMarkers with per-feature color.
         */
        pointToLayer: function(feature, latlng) {
            var props = feature.properties || {};
            var color = props.color || "#000000";
            var radius = props.radius || 8;
            return L.circleMarker(latlng, {
                radius: radius,
                color: color,
                fillColor: color,
                fillOpacity: 0.8,
                weight: 2,
                opacity: 1,
                pane: 'scatter-overlay'
            });
        },

        /**
         * Bind tooltips to scatter overlay features showing sample, habitat, city.
         */
        onEachScatterFeature: function(feature, layer) {
            var props = feature.properties || {};
            var parts = [];
            if (props.sample) {
                parts.push("<b>Sample:</b> " + props.sample);
            }
            if (props.name) {
                parts.push("<b>Name:</b> " + props.name);
            }
            if (props.habitat) {
                parts.push("<b>Habitat:</b> " + props.habitat);
            }
            if (props.city) {
                parts.push("<b>City:</b> " + props.city);
            }
            if (parts.length > 0) {
                layer.bindTooltip(parts.join("<br>"), {
                    sticky: true,
                    direction: "top",
                    opacity: 0.9
                });
            }
        }
    }
});

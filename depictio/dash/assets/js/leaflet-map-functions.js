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
            return {
                fillColor: fillColor,
                color: fillColor,
                weight: 0.5,
                opacity: 0.8,
                fillOpacity: 0.6
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
        }
    }
});

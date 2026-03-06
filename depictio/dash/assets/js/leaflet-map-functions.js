
/**
 * Leaflet map JavaScript functions for dash-leaflet GeoJSON styling and interaction.
 * Used via dash_extensions.javascript.Namespace references.
 */

/**
 * Interpolate between color stops for continuous metrics.
 * stops: array of [position, "#hex"] pairs, sorted by position.
 * t: normalized value 0-1.
 * Returns hex color string.
 */
function _interpolateColorStops(stops, t) {
    if (!stops || stops.length === 0) return "#888888";
    t = Math.max(0, Math.min(1, t));
    if (stops.length === 1) return stops[0][1];

    // Find surrounding pair
    var lower = stops[0], upper = stops[stops.length - 1];
    for (var i = 0; i < stops.length - 1; i++) {
        if (t >= stops[i][0] && t <= stops[i + 1][0]) {
            lower = stops[i];
            upper = stops[i + 1];
            break;
        }
    }

    var range = upper[0] - lower[0];
    var frac = range > 0 ? (t - lower[0]) / range : 0;

    // Parse hex colors
    function parseHex(hex) {
        hex = hex.replace("#", "");
        return {
            r: parseInt(hex.substring(0, 2), 16),
            g: parseInt(hex.substring(2, 4), 16),
            b: parseInt(hex.substring(4, 6), 16)
        };
    }
    var c1 = parseHex(lower[1]), c2 = parseHex(upper[1]);
    var r = Math.round(c1.r + (c2.r - c1.r) * frac);
    var g = Math.round(c1.g + (c2.g - c1.g) * frac);
    var b = Math.round(c1.b + (c2.b - c1.b) * frac);

    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

window.dashExtensions = Object.assign({}, window.dashExtensions, {
    map: {
        /**
         * Per-feature style function. Supports both categorical (color_map lookup)
         * and continuous (color_stops interpolation) modes via hideout config.
         */
        styleFunction: function(feature, context) {
            var props = feature.properties || {};
            var hideout = context.hideout || {};
            var colorProp = hideout.color_prop || "land_cover";
            var value = props[colorProp];
            var fillOpacity = hideout.fill_opacity !== undefined ? hideout.fill_opacity : 0.6;
            var fillColor;

            if (hideout.color_type === "continuous" && hideout.color_stops) {
                var colorMin = hideout.color_min !== undefined ? hideout.color_min : 0;
                var colorMax = hideout.color_max !== undefined ? hideout.color_max : 1;
                var t = (parseFloat(value) - colorMin) / (colorMax - colorMin);
                t = Math.max(0, Math.min(1, isNaN(t) ? 0 : t));
                fillColor = _interpolateColorStops(hideout.color_stops, t);
            } else {
                var colorMap = hideout.color_map || {};
                var defaultColor = hideout.default_color || "#888888";
                fillColor = colorMap[value || ""] || defaultColor;
            }

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

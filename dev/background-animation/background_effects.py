"""
Smooth triangle background animation system for Depictio dashboards.
Based on the refined animation patterns from the existing auth page system.
"""

from dash import Input, Output, State, dcc, html


def create_dashboard_background_effects(theme="light", performance_level="medium"):
    """
    Create smooth triangle background effects based on the existing refined animation system.

    Args:
        theme: "light" or "dark" theme
        performance_level: "low", "medium", or "high" based on device capabilities
    """

    # Depictio brand colors - exactly matching the existing system
    colors = {
        "purple": "#8B5CF6",
        "violet": "#A855F7",
        "blue": "#3B82F6",
        "teal": "#14B8A6",
        "green": "#10B981",
        "yellow": "#F59E0B",
        "orange": "#F97316",
        "pink": "#EC4899",
        "red": "#EF4444",
    }

    # Triangle sizes - exactly matching the existing system
    sizes = {
        "small": {"width": 12, "height": 12, "weight": 0.35},
        "medium": {"width": 18, "height": 18, "weight": 0.3},
        "large": {"width": 24, "height": 24, "weight": 0.25},
        "xlarge": {"width": 32, "height": 32, "weight": 0.1},
    }

    # Performance-based particle counts
    particle_counts = {"low": 15, "medium": 25, "high": 35}
    num_particles = particle_counts.get(performance_level, 25)

    # Generate SVG triangles - exact same method as existing system
    def create_triangle_svg(size_key, color_hex):
        size_info = sizes[size_key]
        w, h = size_info["width"], size_info["height"]

        # Depictio-style triangle with 2:1 ratio - exact same as existing
        svg_path = (
            f"M{w / 2} {h * 0.05} L{w * 0.8} {h * 0.9} Q{w / 2} {h * 0.95} {w * 0.2} {h * 0.9} Z"
        )

        return f"""url("data:image/svg+xml,%3Csvg width='{w}' height='{h}' viewBox='0 0 {w} {h}' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='{svg_path}' fill='{color_hex.replace("#", "%23")}' /%3E%3C/svg%3E")"""

    # Create triangle particles
    triangle_particles = []

    # Grid-based distribution for even coverage - matching existing system
    grid_cols = 6
    grid_rows = 4

    for i in range(num_particles):
        # Choose size based on weights - matching existing system
        cumulative_weight = 0
        rand_val = (i * 0.37) % 1

        chosen_size = "small"
        for size_key, size_info in sizes.items():
            cumulative_weight += size_info["weight"]
            if rand_val <= cumulative_weight:
                chosen_size = size_key
                break

        # Choose color - matching existing system
        color_keys = list(colors.keys())
        color_key = color_keys[i % len(color_keys)]
        color_hex = colors[color_key]

        # Better distribution using grid + randomization - matching existing system
        cell_width = 85 / grid_cols
        cell_height = 70 / grid_rows

        cell_x = i % grid_cols
        cell_y = (i // grid_cols) % grid_rows

        base_x = cell_x * cell_width + cell_width / 2
        base_y = cell_y * cell_height + cell_height / 2

        # Add pseudo-random offset - matching existing system
        offset_x = ((i * 37 + i * i * 13) % 100 - 50) / 100 * cell_width * 0.8
        offset_y = ((i * 41 + i * i * 19) % 100 - 50) / 100 * cell_height * 0.8

        x = max(5, min(90, base_x + offset_x + 7.5))
        y = max(10, min(80, base_y + offset_y + 15))

        # Choose animation pattern - now using refined dashboard animations
        animation_class = f"dashboard-triangle-anim-{i % 6}"

        # Create triangle element
        triangle = html.Div(
            className=f"triangle-particle triangle-{chosen_size} {animation_class}",
            style={
                "left": f"{x}%",
                "top": f"{y}%",
                "background": create_triangle_svg(chosen_size, color_hex),
                "backgroundSize": "contain",
                "backgroundRepeat": "no-repeat",
                "transform": f"rotate({(i * 73) % 360}deg) translateZ(0)",
                "animationDelay": f"{(i * 0.4) % 8}s",  # Reduced max delay to 8s
                "animationDuration": f"{12 + (i * 1.2) % 8}s",  # 12-20s range
                "opacity": "0.3",
            },
        )
        triangle_particles.append(triangle)

    return html.Div(
        [
            # Triangle particles container
            html.Div(
                triangle_particles,
                id="dashboard-triangle-particles",
                className="triangle-particles-container",
                style={
                    "position": "absolute",
                    "top": 0,
                    "left": 0,
                    "right": 0,
                    "bottom": 0,
                    "zIndex": 1,
                    "pointerEvents": "none",
                    "overflow": "hidden",
                },
            ),
            # Performance monitor (hidden)
            dcc.Store(
                id="dashboard-performance-monitor", data={"fps": 60, "level": performance_level}
            ),
            dcc.Store(id="dashboard-background-theme-store", data={"theme": theme}),
            # Interval for performance monitoring
            dcc.Interval(
                id="dashboard-performance-interval",
                interval=5000,  # Check every 5 seconds
                n_intervals=0,
            ),
        ],
        id="dashboard-background-effects",
        style={
            "position": "absolute",
            "top": 0,
            "left": 0,
            "right": 0,
            "bottom": 0,
            "zIndex": 0,
            "pointerEvents": "none",
            "overflow": "hidden",
        },
    )


def create_dashboard_background_styles():
    """Generate additional CSS styles for dashboard background effects."""
    # Return empty div since we'll add the styles to the existing CSS file
    return html.Div()


def register_dashboard_background_callbacks(app):
    """Register callbacks for modern floating orb background effects management."""

    # Performance monitoring callback
    app.clientside_callback(
        """
        function(n_intervals, performance_data) {
            if (typeof performance === 'undefined') {
                return window.dash_clientside.no_update;
            }
            
            // Simple FPS monitoring
            const now = performance.now();
            if (!window.dashboardBackgroundData) {
                window.dashboardBackgroundData = {
                    lastTime: now,
                    frameCount: 0,
                    fps: 60
                };
                return window.dash_clientside.no_update;
            }
            
            const data = window.dashboardBackgroundData;
            data.frameCount++;
            
            if (now - data.lastTime >= 3000) {
                data.fps = Math.round((data.frameCount * 1000) / (now - data.lastTime));
                data.frameCount = 0;
                data.lastTime = now;
                
                // Adjust performance level based on FPS
                let newLevel = performance_data.level;
                if (data.fps < 30 && performance_data.level === 'high') {
                    newLevel = 'medium';
                } else if (data.fps < 20 && performance_data.level === 'medium') {
                    newLevel = 'low';
                } else if (data.fps > 50 && performance_data.level === 'low') {
                    newLevel = 'medium';
                } else if (data.fps > 60 && performance_data.level === 'medium') {
                    newLevel = 'high';
                }
                
                return {
                    fps: data.fps,
                    level: newLevel
                };
            }
            
            return window.dash_clientside.no_update;
        }
        """,
        Output("dashboard-performance-monitor", "data"),
        Input("dashboard-performance-interval", "n_intervals"),
        State("dashboard-performance-monitor", "data"),
    )

    # Theme change callback
    app.clientside_callback(
        """
        function(theme_store, background_theme_store) {
            if (!theme_store) {
                return window.dash_clientside.no_update;
            }
            
            const theme = theme_store.colorScheme || theme_store.theme || 'light';
            const container = document.getElementById('dashboard-background-effects');
            
            if (container) {
                // Update theme classes
                const body = document.body;
                body.classList.remove('theme-light', 'theme-dark');
                body.classList.add(`theme-${theme}`);
                
                return {
                    theme: theme
                };
            }
            
            return window.dash_clientside.no_update;
        }
        """,
        Output("dashboard-background-theme-store", "data"),
        Input("theme-store", "data"),
        State("dashboard-background-theme-store", "data"),
    )

    # Performance level adjustment callback
    app.clientside_callback(
        """
        function(performance_data) {
            if (!performance_data) {
                return window.dash_clientside.no_update;
            }
            
            const container = document.getElementById('dashboard-background-effects');
            if (container) {
                const body = document.body;
                
                // Remove existing performance classes
                body.classList.remove('performance-low', 'performance-medium', 'performance-high', 'low-performance');
                
                // Add new performance class
                body.classList.add(`performance-${performance_data.level}`);
                
                // Add low-performance class for extreme cases
                if (performance_data.fps < 15) {
                    body.classList.add('low-performance');
                }
                
                return {
                    display: 'block'
                };
            }
            
            return window.dash_clientside.no_update;
        }
        """,
        Output("dashboard-triangle-particles", "style"),
        Input("dashboard-performance-monitor", "data"),
    )


def detect_device_performance():
    """Client-side function to detect device performance capabilities."""
    return """
    function detectPerformanceLevel() {
        // Check for hardware acceleration support
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        
        if (!gl) {
            return 'low';
        }
        
        // Check GPU renderer
        const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        if (debugInfo) {
            const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
            
            // Basic GPU detection
            if (renderer.toLowerCase().includes('intel')) {
                return 'medium';
            } else if (renderer.toLowerCase().includes('nvidia') || renderer.toLowerCase().includes('amd')) {
                return 'high';
            }
        }
        
        // Check device memory (if available)
        if (navigator.deviceMemory) {
            if (navigator.deviceMemory >= 8) return 'high';
            if (navigator.deviceMemory >= 4) return 'medium';
            return 'low';
        }
        
        // Check CPU cores
        if (navigator.hardwareConcurrency) {
            if (navigator.hardwareConcurrency >= 8) return 'high';
            if (navigator.hardwareConcurrency >= 4) return 'medium';
            return 'low';
        }
        
        return 'medium'; // Default fallback
    }
    
    // Store performance level globally
    window.depictioPerformanceLevel = detectPerformanceLevel();
    """

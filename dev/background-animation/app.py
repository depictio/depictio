"""
Background Animation Prototype - Using exact code from users_management.py
"""

import dash
import dash_mantine_components as dmc
from dash import dcc, html

# Initialize Dash app
app = dash.Dash(__name__)

def create_triangle_background():
    """
    Create GPU-optimized triangle particle background for Depictio
    Reduced particles and efficient animations for better performance
    """

    # Depictio brand colors
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

    # Triangle sizes - 2:1 ratio (equal sides : short side)
    sizes = {
        "small": {"width": 12, "height": 12, "weight": 0.35},  # 35% small
        "medium": {"width": 18, "height": 18, "weight": 0.3},  # 30% medium
        "large": {"width": 24, "height": 24, "weight": 0.25},  # 25% large
        "xlarge": {"width": 32, "height": 32, "weight": 0.1},  # 10% xlarge
    }

    # Animation types
    animations = [
        "triangle-anim-1",
        "triangle-anim-2",
        "triangle-anim-3",
        "triangle-anim-4",
        "triangle-anim-5",
        "triangle-anim-6",
    ]

    # Generate SVG triangles for each size with 2:1 ratio (equal sides : short side)
    def create_triangle_svg(size_key, color_hex):
        size_info = sizes[size_key]
        w, h = size_info["width"], size_info["height"]

        # Depictio-style triangle with 2:1 ratio
        # Equal sides are ~2x the short side (base)
        # Make triangle taller and more pointed for proper ratio

        # Create isosceles triangle with curved base for organic Depictio feel
        svg_path = (
            f"M{w / 2} {h * 0.05} L{w * 0.8} {h * 0.9} Q{w / 2} {h * 0.95} {w * 0.2} {h * 0.9} Z"
        )

        return f"""url("data:image/svg+xml,%3Csvg width='{w}' height='{h}' viewBox='0 0 {w} {h}' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='{svg_path}' fill='{color_hex.replace("#", "%23")}' /%3E%3C/svg%3E")"""

    # Generate particles with better distribution across full background
    triangle_particles = []
    num_particles = 40  # Increased to 40 triangles as requested

    # Use a combination of grid-based and pseudo-random distribution for even coverage
    grid_cols = 8  # 8 columns
    grid_rows = 5  # 5 rows

    for i in range(num_particles):
        # Choose size based on weights
        cumulative_weight = 0
        rand_val = (i * 0.37) % 1  # Deterministic "random" for consistent results

        chosen_size = "small"
        for size_key, size_info in sizes.items():
            cumulative_weight += size_info["weight"]
            if rand_val <= cumulative_weight:
                chosen_size = size_key
                break

        # Choose color
        color_keys = list(colors.keys())
        color_key = color_keys[i % len(color_keys)]
        color_hex = colors[color_key]

        # Better distribution using grid + randomization
        # Divide screen into grid cells, place particles with random offset
        cell_width = 85 / grid_cols  # 85% width divided by columns
        cell_height = 70 / grid_rows  # 70% height divided by rows

        # Calculate which cell this particle belongs to
        cell_x = i % grid_cols
        cell_y = (i // grid_cols) % grid_rows

        # Base position in cell center
        base_x = cell_x * cell_width + cell_width / 2
        base_y = cell_y * cell_height + cell_height / 2

        # Add pseudo-random offset within cell (deterministic but varied)
        offset_x = ((i * 37 + i * i * 13) % 100 - 50) / 100 * cell_width * 0.8
        offset_y = ((i * 41 + i * i * 19) % 100 - 50) / 100 * cell_height * 0.8

        # Final positions with bounds checking
        x = max(5, min(90, base_x + offset_x + 7.5))
        y = max(10, min(80, base_y + offset_y + 15))

        # Choose animation
        animation_class = animations[i % len(animations)]

        # Create triangle element
        triangle = html.Div(
            className=f"triangle-particle triangle-{chosen_size} {animation_class}",
            style={
                "left": f"{x}%",
                "top": f"{y}%",
                "background": create_triangle_svg(chosen_size, color_hex),
                # Set initial rotation as CSS custom property
                "--initial-rotation": f"{(i * 73) % 360}deg",
                # Initial transform with random rotation
                "transform": f"rotate({(i * 73) % 360}deg) translateZ(0)",
                # Staggered animation delays for dynamic feel
                "animationDelay": f"{(i * 0.2) % 3}s",
            },
        )

        triangle_particles.append(triangle)

    # Return the complete background structure
    return html.Div(
        id="auth-background",
        style={
            "position": "fixed",
            "top": "0",
            "left": "0",
            "width": "100vw",
            "height": "100vh",
            "zIndex": "9998",
            "overflow": "hidden",
        },
        children=[
            html.Div(
                id="triangle-particles",
                style={
                    "position": "absolute",
                    "width": "100%",
                    "height": "100%",
                },
                children=triangle_particles,
            )
        ],
    )

# Simple layout with just the background
app.layout = dmc.MantineProvider([
    create_triangle_background()
])

if __name__ == "__main__":
    app.run(debug=True, port=8051)
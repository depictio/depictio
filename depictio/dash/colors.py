# Depictio brand colors extracted from logo

# Main color palette
colors = {
    "purple": "#9966CC",
    "violet": "#7A5DC7",
    "blue": "#6495ED",
    "teal": "#45B8AC",
    "green": "#8BC34A",
    "yellow": "#F9CB40",
    "orange": "#F68B33",
    "pink": "#E6779F",
    "red": "#E53935",  # Added complementary red
    "black": "#000000",
}

# Color combinations for various chart types
color_sequences = {
    "main": [colors["purple"], colors["blue"], colors["teal"], colors["green"], colors["yellow"], colors["orange"]],
    "cool": [colors["purple"], colors["violet"], colors["blue"], colors["teal"]],
    "warm": [colors["yellow"], colors["orange"], colors["red"], colors["pink"]],
    "alert": [colors["green"], colors["yellow"], colors["orange"], colors["red"]],
    "gradient": [colors["purple"], colors["blue"], colors["teal"], colors["green"], colors["yellow"], colors["orange"]],
}

# Template for Dash
template = {
    "layout": {
        "colorway": color_sequences["main"],
        "font": {"color": colors["black"]},
        "title": {"font": {"color": colors["black"]}},
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
        "colorscale": {"sequential": [[0, colors["purple"]], [1.0, colors["orange"]]]},
    }
}
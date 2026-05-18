"""Plotly theme helpers (extracted from depictio.dash.modules.figure_component.utils).

Lives under api/v1/services/ so the celery prerender tasks can import it
without dragging in the Dash modules. The template names map to mantine
themes registered at app startup via dmc.add_figure_templates().
"""


def get_theme_template(theme: str) -> str:
    """Return the Plotly template name for the given UI theme.

    Args:
        theme: theme name (e.g. "light", "dark"); empty / falsy values fall back to light.

    Returns:
        "mantine_light" or "mantine_dark".
    """
    if not theme or theme == {} or theme == "{}":
        theme = "light"
    return "mantine_dark" if theme == "dark" else "mantine_light"

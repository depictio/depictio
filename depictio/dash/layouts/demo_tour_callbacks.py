"""
Demo Tour Callbacks Module.

This module registers callbacks for the guided tour feature in demo mode.
Handles tour step progression, skip functionality, and state persistence.
"""

import dash
from dash import ALL, Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger


def register_demo_tour_callbacks(app: dash.Dash) -> None:
    """
    Register callbacks for demo tour functionality.

    Callbacks handle:
    - Updating tour state on button clicks
    - Persisting tour state to localStorage via demo-tour-store
    - Server-side callback to control popover visibility

    Args:
        app: The Dash application instance to register callbacks with.
    """
    logger.debug("Registering demo tour callbacks")

    @app.callback(
        Output("demo-tour-store", "data"),
        [
            Input({"type": "tour-next-button", "index": ALL}, "n_clicks"),
            Input({"type": "tour-prev-button", "index": ALL}, "n_clicks"),
            Input({"type": "tour-skip-button", "index": ALL}, "n_clicks"),
            Input({"type": "tour-skip-button-btn", "index": ALL}, "n_clicks"),
            Input("url", "pathname"),
        ],
        [
            State("demo-tour-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def handle_tour_state(
        next_clicks: list,
        prev_clicks: list,
        skip_clicks: list,
        skip_btn_clicks: list,
        pathname: str,
        tour_data: dict | None,
    ):
        """
        Handle tour state updates.

        Args:
            next_clicks: List of click counts for "Next" buttons.
            prev_clicks: List of click counts for "Previous" buttons.
            skip_clicks: List of click counts for "Skip Tour" buttons (icon).
            skip_btn_clicks: List of click counts for "Skip Tour" buttons (text).
            pathname: Current URL pathname.
            tour_data: Current tour state from localStorage.

        Returns:
            Updated tour_data dict.
        """
        # Initialize tour data if None
        if tour_data is None:
            tour_data = {
                "tour_step": 0,
                "tour_completed": False,
                "show_hints": True,
            }

        # Get triggered component
        triggered_id = ctx.triggered_id

        # If tour is completed, return
        if tour_data.get("tour_completed", False):
            return tour_data

        # Handle button clicks (pattern matching IDs)
        if triggered_id and isinstance(triggered_id, dict):
            current_step = tour_data.get("tour_step", 0)

            # Handle "Next" button clicks
            if triggered_id.get("type") == "tour-next-button":
                step_id = triggered_id.get("index")
                logger.info(
                    f"Demo tour: Next clicked on step '{step_id}' (current_step={current_step})"
                )

                # Advance to next step
                tour_data["tour_step"] = current_step + 1

                # Check if tour is complete (5 steps total: 0-4)
                if tour_data["tour_step"] >= 5:
                    tour_data["tour_completed"] = True
                    logger.info("Demo tour: Tour completed!")

                return tour_data

            # Handle "Previous" button clicks
            elif triggered_id.get("type") == "tour-prev-button":
                step_id = triggered_id.get("index")
                logger.info(
                    f"Demo tour: Previous clicked on step '{step_id}' (current_step={current_step})"
                )

                # Go back to previous step (minimum 0)
                tour_data["tour_step"] = max(0, current_step - 1)
                return tour_data

            # Handle "Skip Tour" button clicks (both icon and text button)
            elif triggered_id.get("type") in ("tour-skip-button", "tour-skip-button-btn"):
                step_id = triggered_id.get("index")
                logger.info(f"Demo tour: Skip clicked on step '{step_id}'")
                tour_data["tour_completed"] = True
                tour_data["show_hints"] = False
                return tour_data

        return tour_data

    # Server-side callback to control welcome popover visibility
    # Popover starts OPEN by default, this callback CLOSES it when step advances or tour completes
    @app.callback(
        Output("tour-popover-welcome-demo", "opened"),
        [Input("demo-tour-store", "data"), Input("url", "pathname")],
        prevent_initial_call=False,
    )
    def control_welcome_popover(tour_data: dict | None, pathname: str):
        """
        Control the welcome tour popover visibility based on tour state and current page.

        The popover is created with opened=True by default. This callback closes it
        when the user advances past step 0 or completes/skips the tour.

        Args:
            tour_data: Tour state from localStorage.
            pathname: Current URL pathname.

        Returns:
            bool: Whether the popover should be opened, or no_update if not on dashboards page.
        """
        on_dashboards_page = pathname == "/dashboards"

        # Only control popover when on dashboards page (where it exists)
        if not on_dashboards_page:
            return dash.no_update

        tour_completed = tour_data and tour_data.get("tour_completed") is True
        show_hints = not tour_data or tour_data.get("show_hints") is not False
        current_step = tour_data.get("tour_step", 0) if tour_data else 0

        # Show welcome popover only on step 0, not completed, and hints enabled
        should_open = current_step == 0 and not tour_completed and show_hints
        logger.debug(f"Welcome popover: step={current_step}, should_open={should_open}")
        return should_open

    # Callback to control floating tour guide visibility and content
    @app.callback(
        [
            Output("demo-tour-floating-guide", "style"),
            Output("demo-tour-guide-content", "children"),
        ],
        [Input("demo-tour-store", "data"), Input("url", "pathname")],
        prevent_initial_call=False,
    )
    def update_floating_tour_guide(tour_data: dict | None, pathname: str):
        """
        Update the floating tour guide visibility and content based on tour state.

        Shows the floating guide for steps 1-4 (step 0 uses the popover).
        Position is determined by the step's position metadata.

        Args:
            tour_data: Tour state from localStorage.
            pathname: Current URL pathname.

        Returns:
            tuple: (style dict for visibility, children list for content)
        """
        from depictio.dash.components.demo_tour import TOUR_STEPS, create_tour_step_content

        hidden_style = {
            "position": "fixed",
            "bottom": "20px",
            "right": "20px",
            "zIndex": 9999,
            "display": "none",
        }

        # Check tour state
        tour_completed = tour_data and tour_data.get("tour_completed") is True
        show_hints = not tour_data or tour_data.get("show_hints") is not False
        current_step = tour_data.get("tour_step", 0) if tour_data else 0

        # Hide if tour is completed, hints disabled, or on step 0 (uses popover)
        if tour_completed or not show_hints or current_step == 0:
            return hidden_style, []

        # For steps 1-4, show the floating guide with dynamic positioning
        if current_step < len(TOUR_STEPS):
            step_configs = list(TOUR_STEPS.values())
            step_config = step_configs[current_step]
            position = step_config.get("position", "bottom-end")

            content = create_tour_step_content(current_step, total_steps=len(TOUR_STEPS))
            visible_style = _get_floating_guide_position_style(position)
            return visible_style, content

        return hidden_style, []


# Position mapping for floating tour guide (module-level constant)
_POSITION_STYLES: dict[str, dict[str, str]] = {
    "bottom": {"bottom": "20px", "left": "50%", "transform": "translateX(-50%)"},
    "bottom-start": {"bottom": "20px", "left": "20px"},
    "bottom-end": {"bottom": "20px", "right": "20px"},
    "top": {"top": "80px", "left": "50%", "transform": "translateX(-50%)"},
    "top-start": {"top": "80px", "left": "20px"},
    "top-end": {"top": "80px", "right": "20px"},
    "left": {"top": "50%", "left": "20px", "transform": "translateY(-50%)"},
    "left-start": {"top": "80px", "left": "20px"},
    "left-end": {"bottom": "20px", "left": "20px"},
    "right": {"top": "50%", "right": "20px", "transform": "translateY(-50%)"},
    "right-start": {"top": "80px", "right": "20px"},
    "right-end": {"bottom": "20px", "right": "20px"},
}


def _get_floating_guide_position_style(position: str) -> dict[str, str | int]:
    """
    Convert position metadata to CSS style for floating tour guide.

    Args:
        position: Position name (e.g., "bottom", "top-end", "left").

    Returns:
        dict: CSS style properties for positioning.
    """
    base: dict[str, str | int] = {
        "position": "fixed",
        "zIndex": 9999,
        "display": "block",
    }
    position_style = _POSITION_STYLES.get(position, _POSITION_STYLES["bottom-end"])
    return {**base, **position_style}

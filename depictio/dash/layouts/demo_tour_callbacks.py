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
        [
            Output("demo-tour-store", "data"),
            Output("tour-popover-welcome-demo", "opened"),
            Output("tour-popover-welcome-demo", "disabled"),
        ],
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
    def handle_tour_state_and_popover(
        next_clicks: list,
        prev_clicks: list,
        skip_clicks: list,
        skip_btn_clicks: list,
        pathname: str,
        tour_data: dict | None,
    ):
        """
        Handle tour state AND popover visibility in one callback.

        This unified callback eliminates timing issues and dependency cascades
        by controlling both the tour state (localStorage) and popover visibility
        (opened property) in a single atomic operation.

        Args:
            next_clicks: List of click counts for "Next" buttons.
            prev_clicks: List of click counts for "Previous" buttons.
            skip_clicks: List of click counts for "Skip Tour" buttons (icon).
            skip_btn_clicks: List of click counts for "Skip Tour" buttons (text).
            pathname: Current URL pathname.
            tour_data: Current tour state from localStorage.

        Returns:
            tuple: (tour_data dict, popover_opened bool, popover_disabled bool)
        """
        # Initialize on very first visit (empty localStorage)
        if tour_data is None:
            initial_data = {
                "tour_step": 0,
                "tour_completed": False,
                "show_hints": True,
                "welcome_shown": False,
            }
            # Open popover only if on /dashboards
            should_open_popover = pathname == "/dashboards"
            logger.debug(f"Tour initialization: pathname={pathname}, opening={should_open_popover}")
            return initial_data, should_open_popover, False  # Not disabled initially

        triggered_id = ctx.triggered_id

        # Check if this is a real button click or just component addition
        triggered_prop = ctx.triggered_prop_ids if hasattr(ctx, "triggered_prop_ids") else {}
        logger.debug(
            f"Tour callback triggered: triggered_id={triggered_id}, pathname={pathname}, "
            f"tour_completed={tour_data.get('tour_completed', False)}, "
            f"triggered_prop={triggered_prop}"
        )

        # CRITICAL: Check if tour is completed FIRST (before any other logic)
        # This prevents popover from re-opening after skip/completion
        if tour_data.get("tour_completed", False):
            logger.debug("Tour completed - disabling popover entirely")
            return dash.no_update, False, True  # Disabled=True prevents popover from rendering

        # Refresh/initial call after localStorage loaded
        if triggered_id is None:
            # Popover should open if: step 0, not completed, not yet shown, on /dashboards
            should_open_popover = (
                pathname == "/dashboards"
                and tour_data.get("tour_step", 0) == 0
                and not tour_data.get("tour_completed", False)
                and tour_data.get("show_hints", True)
                and not tour_data.get("welcome_shown", False)
            )
            logger.debug(
                f"Tour refresh: step={tour_data.get('tour_step', 0)}, "
                f"welcome_shown={tour_data.get('welcome_shown', False)}, "
                f"should_open={should_open_popover}"
            )
            return dash.no_update, should_open_popover, False  # Not disabled during tour

        # URL changes
        if triggered_id == "url":
            # Mark welcome as shown when navigating away
            if pathname != "/dashboards" and not tour_data.get("welcome_shown"):
                tour_data["welcome_shown"] = True
                return tour_data, False, False  # Close popover, not disabled

            # On /dashboards: only open popover if tour not completed and all conditions met
            if pathname == "/dashboards":
                should_open = (
                    tour_data.get("tour_step", 0) == 0
                    and not tour_data.get("tour_completed", False)
                    and tour_data.get("show_hints", True)
                    and not tour_data.get("welcome_shown", False)
                )
                return dash.no_update, should_open, False  # Not disabled during tour

            # Not on /dashboards: close popover
            return dash.no_update, False, False  # Close but not disabled

        # Button clicks (pattern matching IDs)
        if triggered_id and isinstance(triggered_id, dict):
            # Validate this is actually a tour button
            tour_button_types = {
                "tour-next-button",
                "tour-prev-button",
                "tour-skip-button",
                "tour-skip-button-btn",
            }
            if triggered_id.get("type") not in tour_button_types:
                logger.debug(f"Ignoring non-tour button: {triggered_id}")
                return dash.no_update, dash.no_update, dash.no_update

            # Validate this is an actual click (not component addition)
            # Pattern-matching callbacks can fire when components are added with n_clicks=0
            all_clicks = next_clicks + prev_clicks + skip_clicks + skip_btn_clicks
            if not any(all_clicks) or all(c == 0 or c is None for c in all_clicks):
                logger.debug("Ignoring callback - no actual button clicks detected")
                return dash.no_update, dash.no_update, dash.no_update

            current_step = tour_data.get("tour_step", 0)

            # Next button
            if triggered_id.get("type") == "tour-next-button":
                step_id = triggered_id.get("index")
                logger.info(
                    f"Demo tour: Next clicked on step '{step_id}' (current_step={current_step})"
                )

                tour_data["tour_step"] = current_step + 1
                tour_data["welcome_shown"] = True

                # Check if tour is now completed (step 5+)
                if tour_data["tour_step"] >= 5:
                    tour_data["tour_completed"] = True
                    logger.info("Demo tour: Tour completed!")
                    return tour_data, False, True  # Close and DISABLE popover on completion

                return tour_data, False, False  # Close popover, continue tour

            # Previous button
            elif triggered_id.get("type") == "tour-prev-button":
                step_id = triggered_id.get("index")
                logger.info(
                    f"Demo tour: Previous clicked on step '{step_id}' (current_step={current_step})"
                )

                tour_data["tour_step"] = max(0, current_step - 1)
                # Re-open popover if going back to step 0
                should_reopen = tour_data["tour_step"] == 0 and pathname == "/dashboards"
                if should_reopen:
                    tour_data["welcome_shown"] = False
                return tour_data, should_reopen, False  # Not disabled

            # Skip button
            elif triggered_id.get("type") in ("tour-skip-button", "tour-skip-button-btn"):
                step_id = triggered_id.get("index")
                logger.info(f"Demo tour: Skip clicked on step '{step_id}'")
                tour_data["tour_completed"] = True
                tour_data["show_hints"] = False
                tour_data["welcome_shown"] = True
                return tour_data, False, True  # Close and DISABLE popover permanently

        # Fall-through: unknown trigger, don't change anything
        return dash.no_update, dash.no_update, dash.no_update

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

"""
Demo Tour Component for guided onboarding.

This module provides reusable guided tour popover components using DMC (Dash Mantine Components)
for first-time user onboarding in demo mode.

Usage:
    from depictio.dash.components.demo_tour import create_tour_popover, TOUR_STEPS

    # Wrap a target element with a tour popover
    popover = create_tour_popover(
        target=my_button,
        step_id="create-dashboard",
        title="Create Your First Dashboard",
        description="Click here to start building your first dashboard.",
    )
"""

from typing import Any, Literal, get_args

import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify

# Type for valid popover positions
PopoverPosition = Literal[
    "top",
    "right",
    "bottom",
    "left",
    "top-end",
    "top-start",
    "right-end",
    "right-start",
    "bottom-end",
    "bottom-start",
    "left-end",
    "left-start",
]

# Valid positions derived from the type definition
VALID_POSITIONS: tuple[str, ...] = get_args(PopoverPosition)

# Define tour steps configuration
TOUR_STEPS = {
    "welcome-demo": {
        "step": 0,
        "title": "Welcome to Depictio Demo!",
        "description": "This is a demo instance. Dashboards you create will be automatically removed after 24 hours.",
        "position": "top",
    },
    "example-dashboards": {
        "step": 1,
        "title": "Explore Example Dashboards",
        "description": "Browse and interact with example dashboards to see what's possible. As an anonymous user, you can view but not edit them.",
        "position": "bottom",
    },
    "login-options": {
        "step": 2,
        "title": "Sign In for Full Access",
        "description": "Login as a temporary user (24h session) or via Google to unlock editing features. You can then duplicate any dashboard to make it your own.",
        "position": "top-end",
    },
    "duplicate-dashboard": {
        "step": 3,
        "title": "Duplicate to Edit",
        "description": "Click on 'Actions', then use the 'Duplicate' action to create your own copy of any dashboard. You'll have full editing rights on your copy.",
        "position": "bottom-start",
    },
    "projects-sidebar": {
        "step": 4,
        "title": "Explore Projects",
        "description": "Click 'Projects' to register a temporary project and upload your own data (CSV, Parquet, or DataFrame).",
        "position": "left",
    },
}


def _create_tour_navigation_buttons(
    step_id: str,
    step_number: int,
    total_steps: int,
    final_step_text: str = "Got it!",
) -> dmc.Group:
    """
    Create navigation buttons for tour steps.

    Args:
        step_id: Unique identifier for this tour step.
        step_number: Current step number (0-indexed).
        total_steps: Total number of steps in the tour.
        final_step_text: Text for the final step button.

    Returns:
        dmc.Group: Navigation buttons component.
    """
    is_first_step = step_number == 0
    is_last_step = step_number >= total_steps - 1

    return dmc.Group(
        [
            dmc.Button(
                "Skip Tour",
                id={"type": "tour-skip-button-btn", "index": step_id},
                variant="subtle",
                color="gray",
                size="sm",
            ),
            dmc.Group(
                [
                    dmc.Button(
                        "Previous",
                        id={"type": "tour-prev-button", "index": step_id},
                        variant="outline",
                        color="blue",
                        size="sm",
                        leftSection=DashIconify(icon="mdi:arrow-left", width=16),
                        style={"display": "none"} if is_first_step else {"display": "inline-flex"},
                    ),
                    dmc.Button(
                        final_step_text if is_last_step else "Next",
                        id={"type": "tour-next-button", "index": step_id},
                        variant="filled",
                        color="blue",
                        size="sm",
                        rightSection=DashIconify(
                            icon="mdi:check" if is_last_step else "mdi:arrow-right",
                            width=16,
                        ),
                    ),
                ],
                gap="xs",
            ),
        ],
        justify="space-between",
        gap="xs",
        style={"width": "100%"},
    )


def _create_tour_content(
    step_id: str,
    title: str,
    description: str,
    step_number: int,
    total_steps: int,
    final_step_text: str = "Got it!",
) -> dmc.Stack:
    """
    Create the content for a tour step (used by both popover and floating guide).

    Args:
        step_id: Unique identifier for this tour step.
        title: Step title.
        description: Step description.
        step_number: Current step number (0-indexed).
        total_steps: Total number of steps.
        final_step_text: Text for the final step button.

    Returns:
        dmc.Stack: Tour step content component.
    """
    return dmc.Stack(
        [
            # Header with step indicator and close button
            dmc.Group(
                [
                    dmc.Badge(
                        f"Step {step_number + 1} of {total_steps}",
                        variant="light",
                        color="blue",
                        size="sm",
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:close", width=18),
                        id={"type": "tour-skip-button", "index": step_id},
                        variant="subtle",
                        color="gray",
                        size="sm",
                    ),
                ],
                justify="space-between",
                style={"width": "100%"},
            ),
            # Title
            dmc.Text(title, fw="bold", size="md"),
            # Description
            dmc.Text(description, size="sm", c="dimmed", style={"lineHeight": 1.5}),
            # Navigation buttons
            _create_tour_navigation_buttons(step_id, step_number, total_steps, final_step_text),
        ],
        gap="xs",
        style={
            "padding": "8px",
            "minWidth": "300px",
            "maxWidth": "400px",
        },
    )


def create_tour_popover(
    target: Any,
    step_id: str,
    title: str | None = None,
    description: str | None = None,
    position: PopoverPosition = "bottom",
    total_steps: int = 1,
    popover_id: str | None = None,
) -> dmc.Popover:
    """
    Create a guided tour popover that wraps a target element.

    The popover starts closed and is opened by a clientside callback after
    the page loads. This ensures proper DOM positioning.

    Args:
        target: The Dash component to wrap with the popover.
        step_id: Unique identifier for this tour step.
        title: Popover title (optional, uses TOUR_STEPS config if None).
        description: Popover description (optional, uses TOUR_STEPS config if None).
        position: Popover position relative to target (top, bottom, left, right).
        total_steps: Total number of steps in the tour (for step indicator).
        popover_id: Optional custom ID for the popover (defaults to f"tour-popover-{step_id}").

    Returns:
        dmc.Popover: A Mantine Popover component wrapping the target.
    """
    step_config = TOUR_STEPS.get(step_id, {})
    step_number = step_config.get("step", 0)

    final_title = title or step_config.get("title", "Tour Step")
    final_description = description or step_config.get("description", "")

    # Use config position if valid, otherwise use provided position
    config_position = step_config.get("position", "bottom")
    final_position: PopoverPosition = (
        config_position if config_position in VALID_POSITIONS else position
    )  # type: ignore[assignment]

    final_popover_id = popover_id or f"tour-popover-{step_id}"

    popover_content = _create_tour_content(
        step_id=step_id,
        title=final_title,
        description=final_description,
        step_number=step_number,
        total_steps=total_steps,
    )

    return dmc.Popover(
        [
            dmc.PopoverTarget(target),
            dmc.PopoverDropdown(
                popover_content,
                style={
                    "backgroundColor": "var(--app-surface-color, #fff)",
                    "border": "1px solid var(--app-border-color, #e0e0e0)",
                    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.15)",
                    "zIndex": 10000,
                },
            ),
        ],
        id=final_popover_id,
        position=final_position,
        withArrow=True,
        shadow="md",
        opened=False,
        trapFocus=False,
        closeOnClickOutside=False,
        zIndex=10000,
    )


def create_tour_popover_simple(
    target: Any,
    step_id: str,
    is_demo_mode: bool = False,
) -> Any:
    """
    Create a simple tour popover or return the target unchanged.

    This is a convenience wrapper that checks demo mode and returns either:
    - The target wrapped in a tour popover (if demo mode is enabled)
    - The target unchanged (if demo mode is disabled)

    Args:
        target: The Dash component to potentially wrap.
        step_id: Unique identifier for this tour step.
        is_demo_mode: Whether demo mode is enabled.

    Returns:
        The target wrapped in a popover (demo mode) or unchanged (normal mode).
    """
    if not is_demo_mode:
        return target

    return create_tour_popover(
        target=target,
        step_id=step_id,
        total_steps=len(TOUR_STEPS),
    )


def create_tour_indicator_badge() -> dmc.Badge:
    """
    Create a small badge indicator showing demo mode is active.

    Returns:
        dmc.Badge: A badge showing "Demo Mode" with a tour icon.
    """
    return dmc.Badge(
        [
            DashIconify(icon="mdi:compass-outline", width=14),
            " Demo Mode",
        ],
        id="demo-mode-indicator",
        variant="light",
        color="violet",
        size="sm",
        style={"cursor": "pointer"},
    )


def create_floating_tour_guide() -> html.Div:
    """
    Create a floating tour guide component that appears in the bottom-right corner.

    This component shows the current tour step and provides navigation.
    It's controlled by callbacks that update its content based on tour state.

    Returns:
        html.Div: A floating guide component.
    """
    return html.Div(
        id="demo-tour-floating-guide",
        children=[
            dmc.Paper(
                id="demo-tour-guide-content",
                children=[],  # Content populated by callback
                shadow="lg",
                radius="md",
                p="md",
                style={
                    "minWidth": "300px",
                    "maxWidth": "400px",
                    "backgroundColor": "var(--app-surface-color, #fff)",
                    "border": "2px solid var(--mantine-color-blue-5)",
                },
            ),
        ],
        style={
            "position": "fixed",
            "bottom": "20px",
            "right": "20px",
            "zIndex": 9999,
            "display": "none",  # Hidden by default, shown by callback
        },
    )


def create_tour_step_content(step: int, total_steps: int = 5) -> list:
    """
    Create the content for a specific tour step (used by floating guide).

    Args:
        step: Current step number (0-indexed).
        total_steps: Total number of steps.

    Returns:
        list: Dash components for the step content.
    """
    step_configs = list(TOUR_STEPS.values())
    if step >= len(step_configs):
        return []

    config = step_configs[step]
    step_id = list(TOUR_STEPS.keys())[step]

    content = _create_tour_content(
        step_id=step_id,
        title=config["title"],
        description=config["description"],
        step_number=step,
        total_steps=total_steps,
        final_step_text="Finish Tour",
    )

    # Return as list (children) for floating guide compatibility
    return [content]


def create_tour_welcome_popover() -> html.Div:
    """
    Create the welcome tour popover as a floating positioned element.

    This creates a floating popover-style element that will be positioned
    near the Create Dashboard button via JavaScript. It's styled like a popover
    but uses absolute positioning instead of DMC Popover component.

    Returns:
        html.Div: Floating popover-style element.
    """
    step_config = TOUR_STEPS.get("welcome-demo", {})
    step_number = step_config.get("step", 0)
    total_steps = len(TOUR_STEPS)

    popover_content = _create_tour_content(
        step_id="welcome-demo",
        title=step_config.get("title", "Welcome to Depictio Demo!"),
        description=step_config.get(
            "description",
            "This is a demo instance. Dashboards you create will be automatically removed after 24 hours.",
        ),
        step_number=step_number,
        total_steps=total_steps,
    )

    return html.Div(
        id="tour-popover-welcome-demo",
        children=[
            dmc.Paper(
                popover_content,
                shadow="lg",
                radius="md",
                p="md",
                style={
                    "backgroundColor": "var(--app-surface-color, #fff)",
                    "border": "2px solid var(--mantine-color-blue-5)",
                    "minWidth": "300px",
                    "maxWidth": "400px",
                },
            ),
        ],
        style={
            "position": "fixed",
            "zIndex": 10000,
            "display": "none",  # Hidden by default, shown by callback
        },
    )


def create_tour_welcome_modal() -> dmc.Modal:
    """
    Create a welcome modal for first-time demo users.

    This modal appears when a user first enters demo mode and explains
    the guided tour feature.

    Returns:
        dmc.Modal: A welcome modal component.
    """
    return dmc.Modal(
        id="demo-welcome-modal",
        title=html.Div(
            [
                DashIconify(icon="mdi:compass", width=24, style={"marginRight": "8px"}),
                "Welcome to Depictio Demo!",
            ],
            style={"display": "flex", "alignItems": "center"},
        ),
        children=[
            dmc.Stack(
                [
                    dmc.Text(
                        "We'll guide you through the key features with helpful tooltips.",
                        size="sm",
                    ),
                    dmc.Text(
                        "You can skip the tour anytime by clicking 'Skip Tour' on any tooltip.",
                        size="xs",
                        c="gray",
                    ),
                    dmc.Group(
                        [
                            dmc.Button(
                                "Skip Tour",
                                id="demo-welcome-skip",
                                variant="outline",
                                color="gray",
                            ),
                            dmc.Button(
                                "Start Tour",
                                id="demo-welcome-start",
                                variant="filled",
                                color="blue",
                                rightSection=DashIconify(icon="mdi:arrow-right", width=16),
                            ),
                        ],
                        justify="flex-end",
                        mt="md",
                    ),
                ],
                gap="sm",
            ),
        ],
        opened=False,
        centered=True,
        size="md",
    )

"""
Analytics tracking component for Dash frontend.
Simplified version - Google Analytics handled via index_string in app_factory.py.
"""

import uuid

from dash import dcc, html


def create_analytics_tracker():
    """
    Create analytics tracking components for the Dash app.
    Only includes session management - no callback triggers needed.
    """
    return html.Div(
        [
            # Store for analytics session management
            dcc.Store(
                id="analytics-session-store",
                storage_type="session",
                data={"session_id": str(uuid.uuid4()), "user_type": "anonymous"},
            ),
        ]
    )

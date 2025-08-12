"""
Analytics tracking component for Dash frontend.
Handles internal analytics tracking. Google Analytics is handled via index_string in app_factory.py.
"""

import uuid

from dash import clientside_callback, dcc, html
from dash.dependencies import Input, Output, State


def create_analytics_tracker():
    """
    Create analytics tracking components for the Dash app.
    """
    return html.Div(
        [
            # Store for analytics session management
            dcc.Store(
                id="analytics-session-store",
                storage_type="session",
                data={"session_id": str(uuid.uuid4()), "user_type": "anonymous"},
            ),
            # Hidden div to trigger analytics
            html.Div(id="analytics-trigger", style={"display": "none"}),
            # Interval for periodic session updates (every 5 minutes)
            dcc.Interval(
                id="analytics-heartbeat",
                interval=5 * 60 * 1000,  # 5 minutes in milliseconds
                n_intervals=0,
            ),
        ]
    )


def register_analytics_callbacks(app):
    """
    Register analytics callbacks for internal tracking.
    Google Analytics is now handled via index_string in app_factory.py.
    """

    # Simplified clientside callback for internal analytics API only
    clientside_callback(
        """
        function(pathname, localData, analyticsSession) {
            console.log('✅ Analytics Callback: Executed for:', pathname);

            try {
                // Get page title
                const pageTitle = document.title || 'Depictio';

                // Determine user type
                let userType = 'anonymous';
                let userId = analyticsSession ? analyticsSession.session_id || 'anon_' + Date.now() : 'anon_' + Date.now();

                if (localData && localData.logged_in) {
                    userType = localData.access_token ? 'authenticated' : 'temporary';
                }

                // Send to internal analytics API only
                const analyticsData = {
                    page_path: pathname || '/',
                    page_title: pageTitle,
                    user_type: userType,
                    user_id: userId,
                    session_id: analyticsSession ? analyticsSession.session_id : null,
                    timestamp: new Date().toISOString()
                };

                fetch('/depictio/api/v1/analytics/track/pageview', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(analyticsData)
                })
                .then(response => response.json())
                .then(data => console.log('📊 Analytics API: Success', data))
                .catch(error => console.warn('📊 Analytics API: Error', error));

                return 'Tracked: ' + pathname + ' (' + userType + ')';

            } catch (error) {
                console.error('❌ Analytics Callback Error:', error);
                return 'Error: ' + error.message;
            }
        }
        """,
        Output("analytics-trigger", "title"),
        [
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),
            State("analytics-session-store", "data"),
        ],
        prevent_initial_call=False,
    )

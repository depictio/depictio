"""
Analytics tracking component for Dash frontend.
"""

import uuid
from datetime import datetime

import requests

from dash import clientside_callback, dcc, html
from dash.dependencies import Input, Output, State
from depictio.api.v1.configs.config import settings


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
    Register all analytics-related callbacks.
    """

    @app.callback(
        Output("analytics-trigger", "children"),
        [
            Input("url", "pathname"),
            Input("url", "search"),
        ],
        [
            State("local-store", "data"),
            State("analytics-session-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def track_page_navigation(pathname, search, local_data, analytics_session):
        """
        Track page navigation events.
        """
        if not settings.analytics.enabled:
            return ""

        try:
            # Determine user type and ID
            user_type = "anonymous"
            user_id = analytics_session.get("session_id", str(uuid.uuid4()))

            if local_data and local_data.get("logged_in"):
                user_type = "authenticated"
                # Try to get user ID from token/local data
                if local_data.get("access_token"):
                    user_type = "authenticated"
                elif local_data.get("temporary_user"):
                    user_type = "temporary"

            # Prepare page view data
            page_data = {
                "page_path": pathname or "/",
                "page_title": None,  # Will be filled by client-side callback
                "user_type": user_type,
                "user_id": user_id,
                "session_id": analytics_session.get("session_id"),
                "referrer": None,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Send to analytics API (async)
            access_token = local_data.get("access_token") if local_data else None
            send_analytics_data(page_data, access_token)

            return f"Tracked: {pathname}"

        except Exception as e:
            print(f"Analytics tracking error: {e}")
            return f"Error: {str(e)}"

    # Client-side callback to get page title and send analytics
    clientside_callback(
        """
        function(pathname, search, localData, analyticsSession) {
            if (!window.analyticsEnabled) {
                return '';
            }

            try {
                // Get page title
                const pageTitle = document.title || 'Depictio';

                // Get referrer
                const referrer = document.referrer || '';

                // Determine user type
                let userType = 'anonymous';
                let userId = analyticsSession.session_id || 'anon_' + Date.now();

                if (localData && localData.logged_in) {
                    userType = localData.access_token ? 'authenticated' : 'temporary';
                }

                // Prepare analytics data
                const analyticsData = {
                    page_path: pathname || '/',
                    page_title: pageTitle,
                    user_type: userType,
                    user_id: userId,
                    session_id: analyticsSession.session_id,
                    referrer: referrer,
                    timestamp: new Date().toISOString()
                };

                // Prepare headers with authentication if available
                const headers = {
                    'Content-Type': 'application/json',
                };

                // Include authorization header if user is authenticated
                if (localData && localData.access_token) {
                    headers['Authorization'] = 'Bearer ' + localData.access_token;
                }

                // Send to analytics API
                fetch('/depictio/api/v1/analytics/track/pageview', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify(analyticsData)
                })
                .then(response => response.json())
                .then(data => {
                    console.log('Analytics tracked:', data);
                })
                .catch(error => {
                    console.warn('Analytics error:', error);
                });

                return 'Tracked: ' + pathname + ' (' + userType + ')';

            } catch (error) {
                console.warn('Analytics client error:', error);
                return 'Client error: ' + error.message;
            }
        }
        """,
        Output("analytics-trigger", "title"),
        [
            Input("url", "pathname"),
            Input("url", "search"),
        ],
        [
            State("local-store", "data"),
            State("analytics-session-store", "data"),
        ],
        prevent_initial_call=False,
    )


def send_analytics_data(page_data, access_token=None):
    """
    Send analytics data to the API (called from server-side callback).

    Args:
        page_data: The analytics data to send
        access_token: Optional authentication token for authenticated users
    """
    try:
        # Get the API base URL
        api_url = f"{settings.fastapi.internal_url}/depictio/api/v1/analytics/track/pageview"

        # Prepare headers
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        # Send POST request
        response = requests.post(api_url, json=page_data, timeout=5, headers=headers)

        if response.status_code == 200:
            print(f"✅ Analytics tracked: {page_data['page_path']} ({page_data['user_type']})")
        else:
            print(f"❌ Analytics API error: {response.status_code}")

    except Exception as e:
        print(f"❌ Analytics request error: {e}")


# Enable analytics in client-side JavaScript
analytics_js = """
// Enable analytics tracking
window.analyticsEnabled = true;

// Track initial page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Analytics tracking enabled');
});
"""


def inject_analytics_script():
    """
    Return JavaScript code to inject into the page for analytics.
    """
    return html.Script(analytics_js)

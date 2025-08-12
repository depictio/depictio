"""
Modular Google Analytics integration for Dash applications.
Based on the pattern from simple_dash_test.py example.
"""

from typing import Optional

from depictio.api.v1.configs.config import settings


class GoogleAnalyticsIntegration:
    """
    Modular Google Analytics integration that generates index_string template
    with proper GA tracking code injection.
    """

    def __init__(self, tracking_id: Optional[str] = None):
        """
        Initialize GA integration.

        Args:
            tracking_id: Google Analytics tracking ID (e.g., 'G-XXXXXXXXXX')
                        If not provided, uses settings.google_analytics.tracking_id
        """
        self.tracking_id = tracking_id or settings.google_analytics.tracking_id
        self.enabled = bool(self.tracking_id and settings.google_analytics.enabled)

    def generate_ga_script(self) -> str:
        """
        Generate Google Analytics tracking script HTML.

        Returns:
            str: Complete GA script HTML or empty string if disabled
        """
        if not self.enabled:
            return ""

        return f"""
        <!-- Global site tag (gtag.js) - Google Analytics -->
        <script async src="https://www.googletagmanager.com/gtag/js?id={self.tracking_id}"></script>
        <script>
          window.dataLayer = window.dataLayer || [];
          function gtag(){{dataLayer.push(arguments);}}
          gtag('js', new Date());

          gtag('config', '{self.tracking_id}');
        </script>"""

    def generate_index_string(self, title: str = "Depictio") -> str:
        """
        Generate complete HTML index string with GA integration.

        Args:
            title: Default page title

        Returns:
            str: Complete HTML template with GA integration
        """
        ga_script = self.generate_ga_script()

        return f"""<!DOCTYPE html>
<html>
    <head>
        {ga_script}
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>"""

    def inject_into_dash_app(self, app, title: str = "Depictio"):
        """
        Inject Google Analytics into a Dash application.

        Args:
            app: Dash application instance
            title: Default page title
        """
        if self.enabled:
            app.index_string = self.generate_index_string(title)
            print(f"✅ Google Analytics integrated with tracking ID: {self.tracking_id}")
        else:
            print("⚠️ Google Analytics integration disabled or no tracking ID provided")


# Global instance for easy import
ga_integration = GoogleAnalyticsIntegration()


def integrate_google_analytics(app, tracking_id: Optional[str] = None, title: str = "Depictio"):
    """
    Convenience function to integrate Google Analytics into a Dash app.

    Args:
        app: Dash application instance
        tracking_id: Optional custom tracking ID
        title: Page title
    """
    integration = GoogleAnalyticsIntegration(tracking_id) if tracking_id else ga_integration
    integration.inject_into_dash_app(app, title)

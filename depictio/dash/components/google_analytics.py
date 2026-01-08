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

        # Inline console filter - must load FIRST before React
        # Intercepts React's internal warning system
        console_filter = """
        <script>
        (function() {
            'use strict';

            // Store original console methods
            const originalWarn = console.warn;
            const originalError = console.error;
            const originalLog = console.log;

            const filtersToSuppress = [
                'defaultProps', 'DraggableWrapper', 'DashGridLayout',
                'bootstrap-autofill-overlay', 'querySelectorAll', 'not a valid selector',
                'overlayBlur', 'overlayOpacity', 'callback ref',
                'dash_mantine_components', 'SyntaxError', 'Failed to execute',
                'CollectAutofillContentService', 'queryElementLabels'
            ];

            function shouldFilter(msg) {
                if (!msg) return false;
                const str = String(msg).toLowerCase();
                return filtersToSuppress.some(f => str.includes(f.toLowerCase()));
            }

            // Override console.warn
            console.warn = function(...args) {
                const msg = args.join(' ');
                if (shouldFilter(msg)) {
                    // Completely suppress
                    return;
                }
                originalWarn.apply(console, args);
            };

            // Override console.error - React warnings come through here
            console.error = function(...args) {
                const msg = args.join(' ');
                if (shouldFilter(msg)) {
                    // Completely suppress
                    return;
                }
                originalError.apply(console, args);
            };

            // Intercept React DOM's warning system at the lowest level
            // React 18 uses a special internal warning function
            const ErrorDescriptor = Object.getOwnPropertyDescriptor(window.console, 'error');
            if (ErrorDescriptor && ErrorDescriptor.configurable) {
                Object.defineProperty(window.console, 'error', {
                    value: function(...args) {
                        const msg = args.join(' ');
                        if (shouldFilter(msg)) return;
                        originalError.apply(console, args);
                    },
                    writable: true,
                    configurable: true
                });
            }

            // Global error handler for browser extension errors
            window.addEventListener('error', function(e) {
                // Check both message and filename (for extension scripts)
                const msg = (e.message || '') + ' ' + (e.filename || '');
                if (shouldFilter(msg)) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }
            }, true);

            // Alternative: window.onerror for catching extension errors
            const originalOnerror = window.onerror;
            window.onerror = function(message, source, lineno, colno, error) {
                const msg = [message, source, error?.message || ''].join(' ');
                if (shouldFilter(msg)) {
                    // Suppress by not calling original handler
                    return true; // Prevents default error handling
                }
                if (originalOnerror) {
                    return originalOnerror(message, source, lineno, colno, error);
                }
                return false;
            };

            // Unhandled promise rejections (for async errors from extensions)
            window.addEventListener('unhandledrejection', function(e) {
                // Check multiple properties where the message might be
                const reason = e.reason || {};
                const msgParts = [
                    String(reason),
                    reason.message || '',
                    reason.stack || '',
                    e.type || ''
                ].join(' ');

                if (shouldFilter(msgParts)) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }
            }, true);

            console.log('✅ Aggressive console filter active (inline)');
        })();
        </script>
        """

        return f"""<!DOCTYPE html>
<html>
    <head>
        {console_filter}
        {ga_script}
        {{%metas%}}
        <title>{{%title%}}</title>
        <link rel="icon" type="image/x-icon" href="/assets/images/icons/favicon.ico">
        <link rel="icon" type="image/png" href="/assets/images/icons/favicon.png">
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

        Also injects console filter (always) to suppress third-party warnings.

        Args:
            app: Dash application instance
            title: Default page title
        """
        # Always inject index_string to include console filter
        # GA script is only included if enabled
        app.index_string = self.generate_index_string(title)

        if self.enabled:
            print(f"✅ Google Analytics integrated with tracking ID: {self.tracking_id}")
        else:
            print("⚠️ Google Analytics disabled, but console filter injected")


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

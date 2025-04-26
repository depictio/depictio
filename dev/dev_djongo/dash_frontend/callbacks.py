from dash import Input, Output, State, callback_context
import json
import dash
from dash.exceptions import PreventUpdate

from auth_modals import auth_modals
from header import create_header
from layouts import home_layout, dashboard_layout, unauthorized_layout, error_layout
import api_calls

def register_callbacks(app):
    """
    Register all callbacks for the Dash app
    """
    
    # Callback to render auth modals
    @app.callback(
        Output("auth-modals", "children"),
        Input("url", "pathname")
    )
    def render_auth_modals(pathname):
        return auth_modals()
    
    # Callback to render header based on authentication state
    @app.callback(
        Output("header", "children"),
        Input("auth-store", "data")
    )
    def render_header(auth_data):
        if auth_data and 'username' in auth_data:
            return create_header(is_authenticated=True, username=auth_data['username'])
        return create_header(is_authenticated=False)
    
    # Callback to handle page routing and OAuth callback
    @app.callback(
        Output("page-content", "children"),
        Output("auth-store", "data", allow_duplicate=True),
        Input("url", "pathname"),
        Input("url", "search"),
        Input("auth-store", "data"),
        prevent_initial_call=True
    )
    def render_page_content(pathname, search, auth_data):
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None
        
        # Check if we're receiving tokens from Google OAuth callback
        if triggered_id == "url" and search:
            import urllib.parse
            params = urllib.parse.parse_qs(search.lstrip('?'))
            
            if 'access_token' in params and 'refresh_token' in params and 'username' in params:
                # Store the tokens in auth-store
                auth_data = {
                    'username': params['username'][0],
                    'access_token': params['access_token'][0],
                    'refresh_token': params['refresh_token'][0]
                }
                # Return home page with updated auth data
                return home_layout(), auth_data
        
        # Normal page routing
        is_authenticated = auth_data and 'access_token' in auth_data
        
        if pathname == "/":
            return home_layout(), dash.no_update
        elif pathname == "/dashboard":
            if is_authenticated:
                return dashboard_layout(), dash.no_update
            else:
                return unauthorized_layout(), dash.no_update
        else:
            return error_layout(f"404 - Page {pathname} not found"), dash.no_update
    
    # Callback to open login modal
    @app.callback(
        Output("login-modal", "is_open"),
        [
            Input("hidden-login-trigger", "n_clicks"),
            Input("login-close", "n_clicks"),
            Input("switch-to-register", "n_clicks"),
            Input("login-button", "n_clicks")
        ],
        [State("login-modal", "is_open")]
    )
    def toggle_login_modal(hidden_trigger_clicks, close_clicks, switch_clicks, login_clicks, is_open):
        ctx = callback_context
        if not ctx.triggered:
            return is_open
        
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        if button_id == "hidden-login-trigger":
            return True
        elif button_id in ["login-close", "switch-to-register", "login-button"]:
            return False
        return is_open
    
    # Callback to open register modal
    @app.callback(
        Output("register-modal", "is_open"),
        [
            Input("switch-to-register", "n_clicks"),
            Input("register-close", "n_clicks"),
            Input("switch-to-login", "n_clicks"),
            Input("register-button", "n_clicks"),
            Input("hidden-register-trigger", "n_clicks")
        ],
        [State("register-modal", "is_open")]
    )
    def toggle_register_modal(switch_clicks, close_clicks, switch_to_login_clicks, register_clicks, hidden_trigger_clicks, is_open):
        ctx = callback_context
        if not ctx.triggered:
            return is_open
        
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        # Only explicitly open when these buttons are clicked
        if button_id == "switch-to-register" or button_id == "hidden-register-trigger":
            return True
        # Close on these button clicks
        elif button_id in ["register-close", "switch-to-login", "register-button"]:
            return False
        # For any other trigger, maintain current state
        return is_open
    
    # Callback to switch between login and register modals
    @app.callback(
        Output("login-modal", "is_open", allow_duplicate=True),
        Output("register-modal", "is_open", allow_duplicate=True),
        Input("switch-to-login", "n_clicks"),
        Input("switch-to-register", "n_clicks"),
        prevent_initial_call=True
    )
    def switch_modals(switch_to_login, switch_to_register):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        if button_id == "switch-to-login":
            return True, False
        elif button_id == "switch-to-register":
            return False, True
        
        raise PreventUpdate
    
    # Callback to handle login
    @app.callback(
        Output("login-alert", "children"),
        Output("login-alert", "color"),
        Output("login-alert", "is_open"),
        Output("auth-store", "data", allow_duplicate=True),
        Input("login-button", "n_clicks"),
        State("login-username", "value"),
        State("login-password", "value"),
        prevent_initial_call=True
    )
    def login_user(n_clicks, username, password):
        if not n_clicks or not username or not password:
            raise PreventUpdate
        
        status_code, response = api_calls.login_user(username, password)
        
        if status_code == 200:
            # Successful login
            auth_data = {
                'username': username,
                'access_token': response['access'],
                'refresh_token': response['refresh']
            }
            return "Login successful!", "success", True, auth_data
        else:
            # Failed login
            error_msg = "Invalid username or password" if status_code == 401 else f"Error: {response}"
            return error_msg, "danger", True, dash.no_update
    
    # Callback to handle registration
    @app.callback(
        Output("register-alert", "children"),
        Output("register-alert", "color"),
        Output("register-alert", "is_open"),
        Input("register-button", "n_clicks"),
        State("register-username", "value"),
        State("register-email", "value"),
        State("register-first-name", "value"),
        State("register-last-name", "value"),
        State("register-password", "value"),
        State("register-password2", "value"),
    )
    def register_user(n_clicks, username, email, first_name, last_name, password, password2):
        if not n_clicks:
            raise PreventUpdate
        
        # Validate inputs
        if not all([username, email, first_name, last_name, password, password2]):
            return "All fields are required", "warning", True
        
        if password != password2:
            return "Passwords do not match", "warning", True
        
        # Print values for debugging
        print(f"Registering user: {username}, {email}, {first_name}, {last_name}")
        
        status_code, response = api_calls.register_user(
            username, email, password, password2, first_name, last_name
        )
        
        if status_code == 201:
            # Successful registration
            return "Registration successful! You can now login.", "success", True
        else:
            # Failed registration
            error_msg = f"Registration failed: {response}"
            print(f"Registration error: {error_msg}")
            return error_msg, "danger", True
    
    # Callback to handle logout
    @app.callback(
        [
            Output("auth-store", "data"),
            Output("login-modal", "is_open", allow_duplicate=True),
            Output("register-modal", "is_open", allow_duplicate=True)
        ],
        Input("logout-button", "n_clicks"),
        State("auth-store", "data"),
        prevent_initial_call=True
    )
    def logout_user(n_clicks, auth_data):
        if not n_clicks or not auth_data:
            raise PreventUpdate
        
        if 'access_token' in auth_data:
            # Call logout API
            api_calls.logout_user(auth_data['access_token'])
        
        # Clear auth data and ensure modals are closed
        return None, False, False
    
    # Callback to redirect to login from unauthorized page
    @app.callback(
        Output("hidden-login-trigger", "n_clicks"),
        Input("redirect-to-login", "n_clicks"),
        prevent_initial_call=True
    )
    def redirect_to_login(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return 1
    
    # Callback to trigger login modal from login button in header
    @app.callback(
        Output("hidden-login-trigger", "n_clicks", allow_duplicate=True),
        Input("login-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def trigger_login_modal(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return 1
    
    # Callback to trigger register modal from register button in header
    @app.callback(
        Output("hidden-register-trigger", "n_clicks"),
        Input("register-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def trigger_register_modal(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return 1
    
    # Callback to directly open login modal from hidden trigger
    @app.callback(
        Output("login-modal", "is_open", allow_duplicate=True),
        Input("hidden-login-trigger", "n_clicks"),
        prevent_initial_call=True
    )
    def open_login_from_trigger(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return True
    
    # Callback to directly open register modal from hidden trigger
    @app.callback(
        Output("register-modal", "is_open", allow_duplicate=True),
        Input("hidden-register-trigger", "n_clicks"),
        prevent_initial_call=True
    )
    def open_register_from_trigger(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return True

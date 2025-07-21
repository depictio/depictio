import inspect
from functools import wraps
from typing import Optional, Union, get_args, get_origin, get_type_hints

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html
from pydantic import BaseModel, ValidationError


# ----- Validation Utilities -----
def convert_to_type(value, target_type):
    """Convert a value to the target type."""
    # Handle None case
    if value is None:
        return None

    # Handle Union types (like Optional)
    origin = get_origin(target_type)
    if origin is Union:
        args = get_args(target_type)
        for arg in args:
            try:
                return convert_to_type(value, arg)
            except Exception:
                continue
        raise ValueError(f"Value {value} could not be converted to any type in {target_type}")

    # Handle primitive types
    if target_type in (str, int, float, bool):
        return target_type(value)

    # Handle Pydantic models
    if inspect.isclass(target_type) and issubclass(target_type, BaseModel):
        if isinstance(value, dict):
            # Let the validation error propagate up
            return target_type.model_validate(value)
        return value

    # Default fallback
    return target_type(value)


def validate_inputs(func):
    """Decorator to validate and convert function inputs based on type hints."""
    type_hints = get_type_hints(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        # Process each argument
        for param_name, param_value in list(bound_args.arguments.items()):
            if param_name in type_hints:
                try:
                    hint_type = type_hints[param_name]
                    bound_args.arguments[param_name] = convert_to_type(param_value, hint_type)
                except ValidationError as ve:
                    # For Pydantic ValidationError, just re-raise it directly
                    # This will preserve all the validation error details
                    raise ve
                except Exception as e:
                    # For other exceptions, create a new ValueError with context
                    error_msg = f"Validation error for {param_name}: {str(e)}"
                    raise ValueError(error_msg) from e

        return func(*bound_args.args, **bound_args.kwargs)

    return wrapper


# ----- Pydantic Model -----
class UserInfo(BaseModel):
    username: str
    age: Optional[int] = None
    is_admin: bool = False


# ----- Dash App -----
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Layout
app.layout = html.Div(
    [
        html.H1("Input Validation Demo"),
        # Input Form
        dbc.Card(
            [
                dbc.CardBody(
                    [
                        html.H3("Enter User Information"),
                        dbc.Input(id="input-name", placeholder="Username", className="mb-2"),
                        dbc.Input(id="input-age", placeholder="Age", className="mb-2"),
                        dbc.Checklist(
                            id="input-admin",
                            options=[{"label": "Is Admin?", "value": True}],
                            className="mb-2",
                        ),
                        dbc.Button("Submit", id="submit-button", color="primary", className="mt-2"),
                    ]
                )
            ],
            className="mb-4",
        ),
        # Output Area
        dbc.Card([dbc.CardHeader("Result"), dbc.CardBody(id="output-area")]),
        # Store for user data
        dcc.Store(id="user-data-store"),
    ]
)


# Create user data and store it
@app.callback(
    Output("user-data-store", "data"),
    Input("submit-button", "n_clicks"),
    State("input-name", "value"),
    State("input-age", "value"),
    State("input-admin", "value"),
    prevent_initial_call=True,
)
def store_user_data(n_clicks, name, age, is_admin):
    if not n_clicks:
        return dash.no_update

    # Create a dictionary that matches our Pydantic model
    return {"username": name, "age": age, "is_admin": bool(is_admin)}


# Process and display the validated data
@app.callback(
    Output("output-area", "children"), Input("user-data-store", "data"), prevent_initial_call=True
)
@validate_inputs
def process_user_data(user_data: UserInfo):
    """
    Process user data after validation.

    Parameters:
    - user_data: A UserInfo Pydantic model validated by our decorator
    """
    # The decorator ensures user_data is a valid UserInfo instance

    # We can safely use the model properties
    username = user_data.username
    age = user_data.age or "Not provided"
    admin_status = "Admin" if user_data.is_admin else "Regular user"

    return [
        html.H4(f"Hello, {username}!"),
        html.P(f"Age: {age}"),
        html.P(f"Status: {admin_status}"),
        html.P(
            "Input was successfully validated through the Pydantic model!", className="text-success"
        ),
    ]


# A simple callback with mixed types
@app.callback(Output("input-name", "valid"), Input("input-name", "value"))
@validate_inputs
def validate_username(username: str):
    """
    Validate the username input.

    Parameters:
    - username: A string type validated by our decorator
    """
    if not username:
        return None

    # username is guaranteed to be a string here
    return len(username) >= 3


if __name__ == "__main__":
    # Enable debug mode - this will enable the error UI
    app.run_server(debug=True)

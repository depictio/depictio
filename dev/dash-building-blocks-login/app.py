from dash import html, Dash, dcc, Input, Output, State
import dash_mantine_components as dmc
import dash

app = Dash(__name__)

app.layout = html.Div([
    dcc.Store(id="modal-state-store", data="login"),  # Store to control modal content state (login or register)
    dcc.Store(id="modal-open-store", data=True),  # Store to control modal state (open or close)
    dmc.Modal(
        id="auth-modal",
        opened=True,
        centered=True,
        children=[
            dmc.Center(id="modal-content")
        ],
        withCloseButton=False,
        closeOnEscape=False,
        closeOnClickOutside=False,
        size="lg"
    ),
        html.Div([
        dmc.Button("hidden-login-button", id="open-login-form", style={'display': 'none'}),
        dmc.Button("hidden-register-button", id="open-register-form", style={'display': 'none'}),
    ])
])

def render_login_form():
    return dmc.Stack([
        dmc.Title('Welcome to DMC/DBC', align='center', order=2),
        dmc.Space(h=20),
        dmc.TextInput(label="Email:", placeholder="Enter your email", style={"width": "100%"}),
        dmc.PasswordInput(label="Password:", placeholder="Enter your password", style={"width": "100%"}),
        dmc.Space(h=20),
        dmc.Group([
            dmc.Button("Login", radius='md', id="login-button", fullWidth=True),
            html.A(dmc.Button("Register", radius='md', variant='outline', color='gray', fullWidth=True), href='#', id="open-login-form", style={'display': 'none'}), 
            html.A(dmc.Button("Register", radius='md', variant='outline', color='gray', fullWidth=True), href='#', id="open-register-form"), 
        ], position="center", mt='1rem')
    ], spacing='1rem', style={"width": "100%"})

def render_register_form():
    return dmc.Stack([
        dmc.Title('Register for DMC/DBC', align='center', order=2),
        dmc.Space(h=20),
        dmc.TextInput(label="Email:", placeholder="Enter your email", style={"width": "100%"}),
        dmc.PasswordInput(label="Password:", placeholder="Enter your password", style={"width": "100%"}),
        dmc.PasswordInput(label="Confirm Password:", placeholder="Confirm your password", style={"width": "100%"}),
        dmc.Space(h=20),
        dmc.Group([
            dmc.Button("Register", radius='md', id="register-button", fullWidth=True),
            html.A(dmc.Button("Back to Login", radius='md', variant='outline', color='gray', fullWidth=True), href='#', id="open-login-form"), 
            html.A(dmc.Button("Back to Login", radius='md', variant='outline', color='gray', fullWidth=True), href='#', id="open-register-form", style={'display': 'none'}), 
        ], position="center", mt='1rem')
    ], spacing='1rem', style={"width": "100%"})

@app.callback(
    Output("auth-modal", "opened"),
    Input("modal-open-store", "data")
)
def open_modal_on_load(open_modal):
    return open_modal

@app.callback(
    Output("modal-content", "children"),
    Input("modal-state-store", "data")
)
def update_modal_content(modal_state):
    if modal_state == "login":
        return render_login_form()
    elif modal_state == "register":
        return render_register_form()
    return html.Div()

@app.callback(
    Output("modal-state-store", "data"),
    [Input("open-register-form", "n_clicks"), Input("open-login-form", "n_clicks")],
    [State("modal-state-store", "data")]
)
def switch_modal_content(n_clicks_register, n_clicks_login, current_state):
    ctx = dash.callback_context

    if not ctx.triggered:
        return current_state

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if button_id == "open-register-form":
        return "register"
    elif button_id == "open-login-form":
        return "login"
    return current_state

if __name__ == '__main__':
    app.run_server(debug=True)

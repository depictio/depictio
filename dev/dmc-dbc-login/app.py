from dash import html, Dash, dcc
import dash_mantine_components as dmc

app = Dash(
    __name__,
    external_stylesheets=[
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.1/css/all.min.css"
    ],
)


app.layout = dmc.Center(
    [
        dmc.Card(
            children=[
                dmc.CardSection(
                    [
                        dmc.Text("Welcome to DMC/DBC, login with", size="lg"),
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Google",
                                    leftIcon=html.I(className="fab fa-google fa-fw fa-lg"),
                                    radius="xl",
                                    variant="outline",
                                ),
                                dmc.Button(
                                    "Twitter",
                                    leftIcon=html.I(className="fab fa-twitter fa-fw fa-lg"),
                                    radius="xl",
                                    variant="outline",
                                ),
                            ],
                            grow=True,
                            mt="1rem",
                            mb="1rem",
                        ),
                        dmc.Divider(
                            label="Or continue with email",
                            variant="dashed",
                            labelPosition="center",
                            mb="1.25rem",
                        ),
                        dmc.Stack(
                            [dmc.TextInput(label="Email:"), dmc.PasswordInput(label="Password:")],
                            spacing="1rem",
                        ),
                        dmc.Group(
                            [
                                dcc.Link(
                                    dmc.Text(
                                        "Don't have an account? Register", color="gray", size="sm"
                                    ),
                                    href="/",
                                ),
                                dmc.Button("Login", radius="md"),
                            ],
                            grow=True,
                            mt="1.5rem",
                            noWrap=True,
                            spacing="apart",
                        ),
                    ],
                    inheritPadding=True,
                )
            ],
            withBorder=True,
            shadow="xl",
            radius="lg",
            p="1.5rem",
            style={"width": "420px"},
        )
    ]
)


if __name__ == "__main__":
    app.run_server(debug=True)

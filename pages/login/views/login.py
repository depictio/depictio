import dash_core_components as dcc
import dash_html_components as html

from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from pages.login.server import app
from pages.login.users_mgt import User
from flask_login import login_user
from werkzeug.security import check_password_hash
from pages.login.config_login import collection
from bson.objectid import ObjectId

layout = dbc.Container(html.Div(
    children=[
        html.Div(
            className="container",
            children=[
                dcc.Location(id='url_login', refresh=True),
                html.Div('''Please log in to continue:''', id='h1'),
                html.Div(
                    # method='Post',
                    children=[
                        dcc.Input(
                            placeholder='Enter your username',
                            n_submit=0,
                            type='text',
                            id='uname-box'
                        ),
                        dcc.Input(
                            placeholder='Enter your password',
                            n_submit=0,
                            type='password',
                            id='pwd-box'
                        ),
                        html.Button(
                            children='Login',
                            n_clicks=0,
                            type='submit',
                            id='login-button'
                        ),
                        html.Div(children='', id='output-state')
                    ]
                ),
            ]
        )
    ]
), fluid=False)



@app.callback(Output('url_login', 'pathname'),
              [Input('login-button', 'n_clicks'),
              Input('uname-box', 'n_submit'),
               Input('pwd-box', 'n_submit')],
              [State('uname-box', 'value'),
               State('pwd-box', 'value')])
def sucess(n_clicks, n_submit_uname, n_submit_pwd, input1, input2):

    if input1 and input2:
        # with Session(engine) as session:
        # statement = select(User).filter_by(username=input1)
        print(input1, input2)
        print(collection.find_one({'username': input1}))
        user_d = collection.find_one({'username': input1})
        user_d_id = str(user_d["_id"])
        user_d_username = user_d["username"]
        user_d_password = user_d["password"]
        user_d_email = user_d["email"]
        user = User(user_d_username, user_d_password, user_d_email, user_d_id)
        print(user)
        if user:
            if check_password_hash(user_d_password, input2):
                login_user(user)
                return '/success'
        else:
            pass
    # else:
    #     return ''



@app.callback(Output('output-state', 'children'),
              [Input('login-button', 'n_clicks'),
               Input('uname-box', 'n_submit'),
               Input('pwd-box', 'n_submit')],
              [State('uname-box', 'value'),
               State('pwd-box', 'value')])
def update_output(n_clicks, n_submit_uname, n_submit_pwd, input1, input2):
    print("XXXXXXXXXXXXXXXX")

    if n_clicks > 0 or n_submit_uname > 0 or n_submit_pwd > 0:
        print(input1, input2)
        print(collection.find_one({'username': input1}))
        user_d = collection.find_one({'username': input1})
        user_d_id = user_d["_id"]
        user_d_username = user_d["username"]
        user_d_password = user_d["password"]
        user_d_email = user_d["email"]
        user = User(user_d_username, user_d_password, user_d_email, user_d_id)
        print(user)
        if user:
            if check_password_hash(user_d_password, input2):
                return ''
            else:
                return 'Incorrect username or password'
        else:
            return 'Incorrect username or password'
    else:
        return ''





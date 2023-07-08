import os
from flask import Flask
from dash import Dash
from flask_login import LoginManager, UserMixin
from pages.login.config_login import client, config, collection
from pages.login.users_mgt import User

app = Dash(
    __name__,
    meta_tags=[
        {
            'charset': 'utf-8',
        },
        {
            'name': 'viewport',
            'content': 'width=device-width, initial-scale=1, shrink-to-fit=no'
        }
    ]
)
server = app.server
app.config.suppress_callback_exceptions = True
app.css.config.serve_locally = True
app.scripts.config.serve_locally = True

# db.init_app(server)

# server.config.update(
#     SECRET_KEY=os.urandom(12),
#     MONGODB_SETTINGS={
#         'db': config.get('database', 'db'),
#         'host': config.get('database', 'host'),
#         'port': config.get('database', 'port')
#     }
# )

server.config.update(
    SECRET_KEY=os.urandom(12),
)




# Create User class with UserMixin



app.config.suppress_callback_exceptions = True

# Setup the LoginManager for the server
login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = '/login'

# print("\n")
# print(User.get("TOTO"))

# @login_manager.user_loader
# def load_user(user_id):
#     print(user_id)
#     user = User.get_by_id(user_id)
#     # user = User.get(user_id)
#     # if user:
#     #     print(user)
#     return user
#     # else:
#     #     print("XXXX")
#     #     return None
    

from bson.objectid import ObjectId

@login_manager.user_loader
def load_user(user_id):
    user_d = collection.find_one({"_id": ObjectId(user_id)})
    user_d_id = str(user_d["_id"])
    user_d_username = user_d["username"]
    user_d_password = user_d["password"]
    user_d_email = user_d["email"]
    u = User(user_d_username, user_d_password, user_d_email, user_d_id)
    print(u)
    if not u:
        return None
    return u
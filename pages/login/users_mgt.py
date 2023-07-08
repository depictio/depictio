import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session
# from depo.common.database import Database
from pages.login.config_login import db, collection as Database
from flask_login import UserMixin
from bson.objectid import ObjectId

class User(UserMixin):

    def __init__(self, username, email, password, _id=None):

        self.username = username
        self.email = email
        self.password = password
        self._id = _id

    def is_authenticated(self):
        return True
    def is_active(self):
        return True
    def is_anonymous(self):
        return False
    def get_id(self):
        return self._id

    @classmethod
    def get_by_username(cls, username):
        data = Database.find_one("users", {"username": username})
        if data is not None:
            return cls(**data)

    @classmethod
    def get_by_email(cls, email):
        data = Database.find_one("users", {"email": email})
        if data is not None:
            return cls(**data)

    @classmethod
    def get_by_id(cls, _id):
        data = Database.find_one("users", {"_id": _id})
        if data is not None:
            return cls(**data)

    @staticmethod
    def login_valid(email, password):
        verify_user = User.get_by_email(email)
        if verify_user is not None:
            return check_password_hash(verify_user.password, password)
        return False

    @classmethod
    def register(cls, username, email, password):
        user = cls.get_by_email(email)
        if user is None:
            new_user = cls( username, email, password)
            new_user.save_to_mongo()
            session['email'] = email
            return True
        else:
            return False

    def json(self):
        return {
            "username": self.username,
            "email": self.email,
            "_id": self._id,
            "password": self.password
        }

    def save_to_mongo(self):
        Database.insert("users", self.json())

# from flask_login import UserMixin
# from werkzeug.security import generate_password_hash, check_password_hash
# from bson.objectid import ObjectId
# from config import db, collection

# class User(UserMixin):
#     def __init__(self, username, password):
#         self.id = username
#         self.username = username
#         self.password = password

#     @staticmethod
#     def get(user_id):
#         user = collection.find_one({'username': user_id})
#         print(user)
#         if not user:
#             return None
#         return User(username=user['username'], password=user['password'])


# class User(UserMixin):

#     def __init__(self, username, email, password, _id=None):
#         self._id = _id
#         self.username = username
#         self.email = email
#         self.password = password

#     @staticmethod
#     def add_user(username, password, email):
#         hashed_password = generate_password_hash(password, method='sha256')

#         new_user = {
#             "username": username, 
#             "email": email, 
#             "password": hashed_password
#         }

#         User.collection.insert_one(new_user)

#     @staticmethod
#     def del_user(username):
#         User.collection.delete_one({"username": username})

#     @staticmethod
#     def show_users():
#         users = User.collection.find({}, {"username": 1, "email": 1})

#         for user in users:
#             print(user)

#     @staticmethod
#     def find_by_id(user_id):
#         user_data = User.collection.find_one({"_id": ObjectId(user_id)})
#         if user_data:
#             return User(user_data["username"], user_data["email"], user_data["password"], user_data["_id"])
#         return None

#     @staticmethod
#     def find_by_username(username):
#         user_data = User.collection.find_one({"username": username})
#         if user_data:
#             return User(user_data["username"], user_data["email"], user_data["password"], user_data["_id"])
#         return None

#     def get_id(self):
#         return str(self._id)

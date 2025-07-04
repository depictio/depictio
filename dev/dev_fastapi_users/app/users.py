from typing import Optional

from beanie import PydanticObjectId
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, models
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from httpx_oauth.clients.google import GoogleOAuth2

from fastapi_users.db import BeanieUserDatabase, ObjectIDIDMixin

from app.db import User, get_user_db

SECRET = "SECRET"

google_oauth_client = GoogleOAuth2(
    "64285070862-0u422mp1n2b0h5n6209u81jgin1ohtjo.apps.googleusercontent.com",
    "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",
)


class UserManager(ObjectIDIDMixin, BaseUserManager[User, PydanticObjectId]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        print(f"User {user.id} has forgot their password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        print(f"Verification requested for user {user.id}. Verification token: {token}")


async def get_user_manager(user_db: BeanieUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy[models.UP, models.ID]:
    strategy = JWTStrategy(secret=SECRET, lifetime_seconds=3600)

    # Monkey patch the generate method to add token logging
    original_generate = strategy.generate

    def logged_generate(*args, **kwargs):
        token = original_generate(*args, **kwargs)
        print(f"Generated JWT Token: {token}")
        return token

    strategy.generate = logged_generate

    return strategy


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, PydanticObjectId](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)

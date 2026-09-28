"""Request-scoped view of the calling token's scopes."""

from contextvars import ContextVar

from depictio.models.models.users import TokenScope, effective_scopes

# Set by ``_async_fetch_user_from_token`` once a Bearer token authenticates.
# ``None`` (the default) covers sessions, legacy tokens and unauthenticated
# requests: all of them keep today's full access.
current_token_scopes: ContextVar[list[TokenScope] | None] = ContextVar(
    "current_token_scopes", default=None
)

# Name and id of that same token, so scoped-token writes carry a readable
# agent name and a stable run id (one per token per day) for the run caps.
current_token_name: ContextVar[str | None] = ContextVar("current_token_name", default=None)
current_token_id: ContextVar[str | None] = ContextVar("current_token_id", default=None)


def set_current_token(scopes: list[TokenScope] | None, name: str | None, token_id: str) -> None:
    current_token_scopes.set(scopes)
    current_token_name.set(name)
    current_token_id.set(token_id)


def request_is_scoped() -> bool:
    """True when the request authenticated with a token limited to scopes."""
    return current_token_scopes.get() is not None


def request_has_scope(scope: TokenScope) -> bool:
    return scope in effective_scopes(current_token_scopes.get())

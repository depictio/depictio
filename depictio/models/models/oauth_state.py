"""Short-lived, single-use state of an OpenID Connect login round-trip.

``/auth/oidc/{provider}/login`` mints a record, the provider sends the browser
back to ``/auth/oidc/{provider}/callback`` with its ``state``, and the callback
consumes the record atomically (``find_one_and_delete``). The two requests are
free to land on different workers or replicas, which is why the record lives in
MongoDB rather than in process memory.
"""

from datetime import datetime

from beanie import Document
from pymongo import IndexModel

from depictio.models.models.base import MongoModel


class OAuthState(MongoModel):
    """What the callback needs to finish the login it was started for.

    ``nonce`` and ``code_verifier`` never leave the server: the browser only
    carries ``state`` (and the IdP the nonce, inside the signed ``id_token``,
    and the PKCE challenge derived from the verifier).
    """

    state: str  # opaque value echoed back by the provider
    expire_datetime: datetime  # naive UTC
    #: Provider id the login was started for; a callback for another one fails.
    provider: str | None = None
    #: Expected ``nonce`` claim of the ``id_token``.
    nonce: str | None = None
    #: PKCE verifier sent with the token request.
    code_verifier: str | None = None
    #: Same-origin path to land on after login (validated when stored).
    return_to: str | None = None


class OAuthStateBeanie(OAuthState, Document):
    class Settings:
        name = "oauth_states"  # Collection name
        indexes = [
            # States are looked up by their value and must be unique.
            IndexModel([("state", 1)], unique=True),
            # TTL index: MongoDB drops a state once it passes ``expire_datetime``,
            # so abandoned login attempts never accumulate, no cleanup job needed.
            IndexModel([("expire_datetime", 1)], expireAfterSeconds=0),
        ]

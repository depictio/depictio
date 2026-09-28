"""Short-lived signed URLs for the genome browser's file reads.

JBrowse fetches track and index files itself, block by block, with plain
``fetch`` calls that carry no ``Authorization`` header. The render endpoint
(which does see the user's token) therefore hands out URLs signed with an HMAC
over what they grant: one role of one track of one data collection, for one
user, until ``exp``. The proxy re-checks the signature and the user's access
to the data collection on every request, so a leaked URL expires, cannot be
widened to another file, and stops working when the user loses access.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from depictio.api.v1.configs.config import settings

_CONTEXT = b"depictio-jbrowse-track-url-v1"


def _key() -> bytes:
    material = settings.auth.internal_api_key.encode("utf-8")
    return hashlib.sha256(_CONTEXT + b":" + material).digest()


def _payload(scope: str, dc_id: str, item: str, role: str, uid: str, exp: int) -> bytes:
    return "|".join((scope, dc_id, item, role, uid, str(exp))).encode("utf-8")


def sign(scope: str, dc_id: str, item: str, role: str, uid: str, exp: int) -> str:
    digest = hmac.new(_key(), _payload(scope, dc_id, item, role, uid, exp), hashlib.sha256)
    return digest.hexdigest()[:40]


def signed_query(scope: str, dc_id: str, item: str, role: str, uid: str) -> str:
    """Query string (without ``?``) granting ``role`` of ``item`` to ``uid``."""
    exp = int(time.time()) + settings.jbrowse.url_ttl_s
    return urlencode({"uid": uid, "exp": exp, "sig": sign(scope, dc_id, item, role, uid, exp)})


def verify(
    scope: str, dc_id: str, item: str, role: str, uid: str | None, exp: str | None, sig: str | None
) -> bool:
    if not (uid and exp and sig) or not exp.isdigit():
        return False
    if int(exp) < time.time():
        return False
    expected = sign(scope, dc_id, item, role, uid, int(exp))
    return hmac.compare_digest(expected, sig)

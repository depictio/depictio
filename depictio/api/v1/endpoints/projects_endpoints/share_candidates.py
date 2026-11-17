"""Finding someone to share a project with.

The sharing dialog used to read the whole user list from ``/auth/list``, an
admin-only route, so an owner or P.I. who is not an admin could not add a person
from another group at all. This module backs a narrower lookup instead: a query
of at least ``MIN_QUERY_LENGTH`` characters returns at most ``MAX_RESULTS``
people, as ``id`` / ``email`` / ``display_name`` and nothing else.

The route that uses it is open only to those who can manage the project's
sharing, so the account directory cannot be probed by anyone else.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

MIN_QUERY_LENGTH = 3
MAX_RESULTS = 10
#: Rows read from the database before ranking: enough that a common substring
#: still leaves the best matches in the page, without scanning every account.
FETCH_LIMIT = 50

#: Fields the lookup reads; the route never hands out anything else.
USER_PROJECTION = {"email": 1, "display_name": 1}


def clean_query(raw: str | None) -> str | None:
    """The trimmed query, or None when it is too short to search with."""
    query = (raw or "").strip()
    return query if len(query) >= MIN_QUERY_LENGTH else None


def _eligible() -> dict[str, Any]:
    """Accounts worth sharing with: not the anonymous user, not deactivated."""
    return {"is_anonymous": {"$ne": True}, "is_active": {"$ne": False}}


def exact_email_filter(query: str) -> dict[str, Any]:
    """Accounts whose email is ``query``, ignoring case."""
    return {
        **_eligible(),
        "email": {"$regex": f"^{re.escape(query)}$", "$options": "i"},
    }


def partial_filter(query: str) -> dict[str, Any]:
    """Accounts whose email, display name or login contains ``query``, ignoring case.

    ``query`` is escaped: it is text typed by a user, never a pattern.
    """
    pattern = {"$regex": re.escape(query), "$options": "i"}
    return {
        **_eligible(),
        "$or": [{"email": pattern}, {"display_name": pattern}, {"login": pattern}],
    }


def rank_candidates(
    docs: Iterable[Mapping[str, Any]], query: str, limit: int = MAX_RESULTS
) -> list[dict[str, str | None]]:
    """De-duplicate, order best match first and trim ``docs`` to ``limit`` people.

    An exact email comes first, then a prefix of the email or the name, then the
    rest by email, so a pasted address is never pushed out of the page.
    """
    needle = query.casefold()
    unique: dict[str, Mapping[str, Any]] = {}
    for doc in docs:
        unique.setdefault(str(doc["_id"]), doc)

    def order(doc: Mapping[str, Any]) -> tuple[int, str]:
        email = str(doc.get("email") or "").casefold()
        name = str(doc.get("display_name") or "").casefold()
        if email == needle:
            return (0, email)
        if email.startswith(needle) or name.startswith(needle):
            return (1, email)
        return (2, email)

    ranked = sorted(unique.values(), key=order)[:limit]
    return [
        {
            "id": str(doc["_id"]),
            "email": str(doc.get("email") or ""),
            "display_name": doc.get("display_name"),
        }
        for doc in ranked
    ]

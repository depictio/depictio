"""The one error the Project Builder core raises for a request it refuses."""

from __future__ import annotations


class BuilderRefused(Exception):
    """A request the builder cannot answer, with the HTTP status and code to answer it with.

    The same ``{detail, code}`` shape as the API's ``CodedHTTPException``, so the
    SPA reads a refusal the same way from the main API and the standalone server.
    """

    def __init__(self, status: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code

    def body(self) -> dict[str, str]:
        body = {"detail": self.detail}
        if self.code:
            body["code"] = self.code
        return body

"""
Custom logging configuration for Depictio API.

Provides formatters that mask sensitive data like tokens in access logs.
"""

import re

from uvicorn.logging import AccessFormatter


class MaskedAccessFormatter(AccessFormatter):
    """Access log formatter that masks sensitive query parameters like tokens."""

    # Pattern to match token query parameters
    TOKEN_PATTERN = re.compile(r"(\?|&)(token|access_token|refresh_token)=([^&\s]+)")

    def formatMessage(self, record):
        """Format the log message, masking any tokens in the request line."""
        # Get the original formatted message
        message = super().formatMessage(record)

        # Mask any tokens in the message
        message = self.TOKEN_PATTERN.sub(r"\1\2=***MASKED***", message)

        return message

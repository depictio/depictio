"""
Custom JSON response handling for FastAPI.

Provides custom serialization for MongoDB ObjectId types.
"""

from typing import Any

from beanie import PydanticObjectId
from bson import ObjectId
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from depictio.models.models.base import PyObjectId


def custom_jsonable_encoder(obj: Any, **kwargs: Any) -> Any:
    """
    Custom JSON encoder that handles ObjectId serialization recursively.

    Args:
        obj: Object to encode
        **kwargs: Additional arguments passed to jsonable_encoder

    Returns:
        JSON-serializable representation of the object
    """
    if isinstance(obj, ObjectId | PydanticObjectId | PyObjectId):
        return str(obj)

    if isinstance(obj, dict):
        return {k: custom_jsonable_encoder(v, **kwargs) for k, v in obj.items()}

    if isinstance(obj, list | tuple | set):
        return [custom_jsonable_encoder(i, **kwargs) for i in obj]

    try:
        return jsonable_encoder(obj, **kwargs)
    except Exception:
        return str(obj)


class CustomJSONResponse(JSONResponse):
    """
    Custom JSON Response class that handles ObjectId serialization.

    Uses a recursive encoder that converts all ObjectId instances to strings.
    """

    def render(self, content: Any) -> bytes:
        """
        Render content to JSON bytes with custom ObjectId handling.

        Args:
            content: Content to render as JSON

        Returns:
            JSON-encoded bytes
        """
        serialized_content = custom_jsonable_encoder(content)
        return super().render(serialized_content)

"""
Custom JSON response handling for FastAPI.

Provides custom serialization for MongoDB ObjectId types and NaN/Inf floats.
"""

import math
from typing import Any

from beanie import PydanticObjectId
from bson import ObjectId
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from depictio.models.models.base import PyObjectId

_PLAIN_TYPES = frozenset({str, int, bool, type(None)})
_NUMERIC_TYPES = frozenset({int, float, bool, type(None)})


def _is_plain_list(items: list) -> bool:
    """Whether ``json.dumps`` can take this list as it is.

    A column of 773k strings or numbers (an advanced_viz frame) went through the
    recursion below one element at a time, a Python call each, which cost several
    seconds and nothing else: none of its elements needs encoding. Exact types,
    so a subclass (an ObjectId wrapper, an enum) still takes the slow path; a
    float list is plain only when every value is finite, since NaN and Inf
    must become null.
    """
    kinds = set(map(type, items))
    if kinds <= _PLAIN_TYPES:
        return True
    if kinds <= _NUMERIC_TYPES:
        return all(math.isfinite(x) for x in items if isinstance(x, float))
    return False


def custom_jsonable_encoder(obj: Any, **kwargs: Any) -> Any:
    """
    Custom JSON encoder that handles ObjectId serialization and NaN/Inf floats recursively.

    Args:
        obj: Object to encode
        **kwargs: Additional arguments passed to jsonable_encoder

    Returns:
        JSON-serializable representation of the object
    """
    if isinstance(obj, ObjectId | PydanticObjectId | PyObjectId):
        return str(obj)

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None

    if isinstance(obj, dict):
        return {k: custom_jsonable_encoder(v, **kwargs) for k, v in obj.items()}

    if type(obj) is list and _is_plain_list(obj):
        return obj

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

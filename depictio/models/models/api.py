from pydantic import BaseModel, Field


class BaseApiResponse(BaseModel):
    """Base class for API responses."""

    success: bool = Field(..., description="Indicates if the API call was successful")
    message: str = Field(..., description="Message associated with the API response")
    # Optional data field for additional information
    data: dict | None = Field(None, description="Optional data field for additional information")

"""
Pydantic models for Google OAuth authentication.

These models define the data structures used for Google OAuth 2.0 authentication flow.
"""

from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class GoogleOAuthRequest(BaseModel):
    """Google OAuth callback request model."""

    code: str = Field(..., description="Authorization code from Google OAuth")
    state: str = Field(..., description="State parameter to prevent CSRF attacks")
    scope: str | None = Field(None, description="OAuth scopes granted by user")
    error: str | None = Field(None, description="Error parameter if OAuth failed")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        """Validate authorization code is present and reasonable length."""
        if not v or len(v) < 10:
            raise ValueError("Authorization code must be at least 10 characters")
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Validate state parameter for CSRF protection."""
        if not v or len(v) < 16:
            raise ValueError("State parameter must be at least 16 characters")
        return v


class GoogleUserInfo(BaseModel):
    """Google user information model from OAuth API response."""

    id: str = Field(..., description="Google user ID")
    email: EmailStr = Field(..., description="User's email address")
    verified_email: bool = Field(..., description="Whether email is verified by Google")
    name: str = Field(..., description="User's full name")
    given_name: str | None = Field(None, description="User's first name")
    family_name: str | None = Field(None, description="User's last name")
    picture: str | None = Field(None, description="URL to user's profile picture")
    locale: str | None = Field(None, description="User's locale")

    @field_validator("email")
    @classmethod
    def validate_email_verified(cls, v: str) -> str:
        """Ensure we only accept verified emails from Google."""
        # Note: We'll check verified_email field in the endpoint logic
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate user name is present."""
        if not v or len(v.strip()) < 1:
            raise ValueError("User name cannot be empty")
        return v.strip()


class GoogleOAuthResponse(BaseModel):
    """Response model for Google OAuth operations."""

    success: bool = Field(..., description="Whether the OAuth operation succeeded")
    message: str = Field(..., description="Human-readable message")
    user_created: bool = Field(..., description="Whether a new user was created")
    user: dict[str, Any] | None = Field(None, description="User information")
    token: dict[str, Any] | None = Field(None, description="Authentication token data")
    redirect_url: str | None = Field(None, description="URL to redirect user to")


class GoogleOAuthLoginResponse(BaseModel):
    """Response model for Google OAuth login initiation."""

    authorization_url: str = Field(..., description="Google OAuth authorization URL")
    state: str = Field(..., description="State parameter for CSRF protection")

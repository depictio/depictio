import os
import re
from typing import Optional
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PolarsStorageOptions(BaseModel):
    endpoint_url: str
    aws_access_key_id: str
    aws_secret_access_key: str
    use_ssl: str = "false"
    signature_version: str = "s3v4"
    region: str = "us-east-1"
    AWS_ALLOW_HTTP: str = "true"
    AWS_S3_ALLOW_UNSAFE_RENAME: str = "true"

    @field_validator("endpoint_url")
    def validate_endpoint_url(cls, v):
        if not v:
            raise ValueError("Endpoint URL cannot be empty")
        if not re.match(r"^https?://[^/]+:\d+", v):
            raise ValueError("Invalid URL format : http://localhost:9000")
        return v

    @field_validator("aws_access_key_id")
    def validate_aws_access_key_id(cls, v):
        if not v:
            raise ValueError("AWS access key ID cannot be empty")
        return v

    @field_validator("aws_secret_access_key")
    def validate_aws_secret_access_key(cls, v):
        if not v:
            raise ValueError("AWS secret access key cannot be empty")
        return v

    @field_validator("use_ssl")
    def validate_use_ssl(cls, v):
        if not isinstance(v, str):
            raise ValueError("use_ssl must be a string")
        if v.lower() not in ["true", "false"]:
            raise ValueError("use_ssl must be 'true' or 'false'")
        return v

    @field_validator("signature_version")
    def validate_signature_version(cls, v):
        if not v:
            raise ValueError("Signature version cannot be empty")
        return v

    @field_validator("region")
    def validate_region(cls, v):
        if not v:
            raise ValueError("Region cannot be empty")
        return v

    @field_validator("AWS_ALLOW_HTTP")
    def validate_AWS_ALLOW_HTTP(cls, v):
        if not isinstance(v, str):
            raise ValueError("AWS_ALLOW_HTTP must be a string")
        if v.lower() not in ["true", "false"]:
            raise ValueError("AWS_ALLOW_HTTP must be 'true' or 'false'")
        return v

    @field_validator("AWS_S3_ALLOW_UNSAFE_RENAME")
    def validate_AWS_S3_ALLOW_UNSAFE_RENAME(cls, v):
        if not isinstance(v, str):
            raise ValueError("AWS_S3_ALLOW_UNSAFE_RENAME must be a string")
        if v.lower() not in ["true", "false"]:
            raise ValueError("AWS_S3_ALLOW_UNSAFE_RENAME must be 'true' or 'false'")
        return v


class S3DepictioCLIConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")
    
    endpoint_url: str = Field(
        default="http://localhost:9000",
        json_schema_extra={"env": "DEPICTIO_MINIO_ENDPOINT_URL"},
    )
    root_user: str = Field(
        default="minio",
        validation_alias=AliasChoices(
            "DEPICTIO_MINIO_ROOT_USER",
            "DEPICTIO_MINIO_ACCESS_KEY",
            "MINIO_ACCESS_KEY",
        ),
    )
    root_password: str = Field(
        default="minio123",
        validation_alias=AliasChoices(
            "DEPICTIO_MINIO_ROOT_PASSWORD",
            "DEPICTIO_MINIO_SECRET_KEY",
            "MINIO_SECRET_KEY",
        ),
    )
    bucket: str = Field(
        default="depictio-bucket", json_schema_extra={"env": "DEPICTIO_MINIO_BUCKET"}
    )


class MinioConfig(S3DepictioCLIConfig):
    """Minio configuration."""

    internal_endpoint: str = Field(
        default="http://minio",
        json_schema_extra={"env": "DEPICTIO_MINIO_INTERNAL_ENDPOINT"},
    )
    external_endpoint: str = Field(
        default="http://localhost",
        json_schema_extra={"env": "DEPICTIO_MINIO_EXTERNAL_ENDPOINT"},
    )
    port: Optional[int] = Field(default=9000, json_schema_extra={"env": "DEPICTIO_MINIO_PORT"})
    secure: bool = Field(default=False, json_schema_extra={"env": "DEPICTIO_MINIO_SECURE"})
    data_dir: str = Field(
        default="/depictio/minio_data",
        json_schema_extra={"env": "DEPICTIO_MINIO_DATA_DIR"},
    )
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_", extra="allow")

    @model_validator(mode="before")
    def configure_endpoint_url(cls, values):
        # Check if running in a container
        is_container = os.getenv("DEPICTIO_CONTAINER", "false").lower() == "true"

        # Get internal and external endpoints
        internal_endpoint = values.get("internal_endpoint", "http://minio")
        external_endpoint = values.get("external_endpoint", "http://localhost")
        port = values.get("port", 9000)

        if is_container:
            if external_endpoint == "http://localhost":
                # If running in a container and external endpoint is localhost, use internal endpoint
                endpoint_url = f"{internal_endpoint}:{port}"
            else:
                if port:
                    endpoint_url = f"{external_endpoint}:{port}"
                else:
                    endpoint_url = external_endpoint
        else:
            if port:
                endpoint_url = f"{external_endpoint}:{port}"
            else:
                endpoint_url = external_endpoint
        values["endpoint_url"] = endpoint_url

        return values

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.logging import logger


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
        if not re.match(r"^https?://[^/]+(:\d+)?$", v):
            raise ValueError(
                "Invalid URL format. Expected format: http://localhost:9000 or https://s3.embl.de"
            )
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


def is_minio_running_in_docker():
    import socket

    try:
        # Try to resolve the 'minio' hostname, which will only work
        # if we're in the same Docker network as the Minio service
        socket.gethostbyname("minio")
        return True
    except socket.gaierror:
        # If the hostname can't be resolved, we're likely not running in Docker
        # or Minio isn't present in the network
        return False


# DOCS: Document the `is_minio_running_in_docker` function
class S3DepictioCLIConfig(BaseSettings):
    """Test-specific version of S3DepictioCLIConfig for isolated testing."""

    service_name: str = Field(default="minio")
    host: str = Field(default="localhost")
    endpoint_url: str = Field(default="http://localhost:9000")
    port: Optional[int] = Field(default=0)
    root_user: str = Field(default="minio")
    root_password: str = Field(default="minio123")
    bucket: str = Field(default="depictio-bucket")
    on_premise_service: Optional[bool] = Field(default=None)
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_")

    @field_validator("on_premise_service", mode="before")
    def set_on_premise_service_default(cls, v):
        """Set default value for on_premise_service only if it's None."""
        logger.debug(f"Setting on_premise_service: {v}")
        if v is None:
            return is_minio_running_in_docker()
        return v

    @model_validator(mode="after")
    def update_endpoint_url_based_on_context(cls, model):
        logger.debug(f"Updating endpoint_url for model: {model}")
        # Extract port from endpoint_url if it contains a port specification
        port_match = re.search(r":(\d+)$", model.endpoint_url)
        logger.debug(f"Port match: {port_match}")
        if port_match:
            model.port = int(port_match.group(1))
        # host_match = re.search(r"^(https?://)?([^:/]+)", model.endpoint_url)
        # logger.debug(f"Host match: {host_match}")
        # if host_match:
        #     model.host = host_match.group(2)

        # Update endpoint_url when in server context and running on premise
        # try:
        # Try to access DEPICTIO_CONTEXT, using a default if not found
        if DEPICTIO_CONTEXT == "server" and model.on_premise_service:
            # Use the correct port value (either extracted or default)
            port = model.port or 9000  # Use default port if not specified
            # If running in server context, use the service name as the endpoint URL
            model.endpoint_url = f"http://{model.service_name}:{port}"
            logger.debug(f"Updated endpoint_url: {model.endpoint_url}")
        else:
            # If not running in server context, use the provided endpoint URL
            logger.debug(f"Using provided endpoint_url: {model.endpoint_url}")
            model.endpoint_url = f"http://{model.host}:{model.port or 9000}"
        # except NameError:
        #     # DEPICTIO_CONTEXT might not be defined, handle gracefully
        #     pass

        return model


# class S3DepictioCLIConfig(S3DepictioCLIConfig):
#     """Minio configuration."""

#     external_endpoint: str = Field(default="http://localhost")
#     port: Optional[int] = Field(default=0)
#     secure: bool = Field(default=False)
#     data_dir: str = Field(default="/depictio/minio_data")
#     model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_")

#     @field_validator("port", mode="before")
#     def validate_port(cls, v):
#         if v == 0:
#             return v
#         if not isinstance(v, int):
#             raise ValueError("Port must be an integer")
#         if v < 1 or v > 65535:
#             raise ValueError("Port must be between 1 and 65535")
#         return v

#     @model_validator(mode="before")
#     def configure_endpoint_url(cls, values):
#         # Check if running in a container
#         is_container = os.getenv("DEPICTIO_CONTAINER", "false").lower() == "true"

#         # Get internal and external endpoints
#         internal_endpoint = values.get("internal_endpoint", "http://minio")
#         external_endpoint = values.get("external_endpoint", "http://localhost")
#         port = values.get("port", 0)

#         if is_container:
#             if external_endpoint == "http://localhost":
#                 # If running in a container and external endpoint is localhost, use internal endpoint
#                 endpoint_url = f"{internal_endpoint}:{port}"
#             else:
#                 if port > 0:
#                     endpoint_url = f"{external_endpoint}:{port}"
#                 else:
#                     endpoint_url = external_endpoint
#         else:
#             if port > 0:
#                 endpoint_url = f"{external_endpoint}:{port}"
#             else:
#                 endpoint_url = external_endpoint

#         logger.debug(f"Endpoint URL: {endpoint_url}")
#         logger.debug(f"Internal Endpoint: {internal_endpoint}")
#         logger.debug(f"Is container: {is_container}")
#         values["endpoint_url"] = endpoint_url

#         return values

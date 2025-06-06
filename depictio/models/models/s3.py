from pydantic import BaseModel, field_validator

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig


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
        return v

    @classmethod
    def from_s3_config(cls, s3_config: S3DepictioCLIConfig) -> "PolarsStorageOptions":
        """Create storage options using a :class:`S3DepictioCLIConfig` instance.

        The ``url`` property of ``S3DepictioCLIConfig`` automatically resolves
        to either the internal service URL or the external URL depending on the
        current ``DEPICTIO_CONTEXT`` environment variable. This makes the
        resulting ``PolarsStorageOptions`` usable from within microservices as
        well as when the package is used externally (e.g. via ``depictio-cli``).
        """

        return cls(
            endpoint_url=s3_config.url,
            aws_access_key_id=s3_config.root_user,
            aws_secret_access_key=s3_config.root_password,
        )


# class PolarsStorageOptions(BaseModel):
#     endpoint_url: str
#     aws_access_key_id: str
#     aws_secret_access_key: str
#     use_ssl: str = "false"
#     signature_version: str = "s3v4"
#     region: str = "us-east-1"
#     AWS_ALLOW_HTTP: str = "true"
#     AWS_S3_ALLOW_UNSAFE_RENAME: str = "true"

#     @field_validator("endpoint_url")
#     def validate_endpoint_url(cls, v):
#         if not v:
#             raise ValueError("Endpoint URL cannot be empty")
#         if not re.match(r"^https?://[^/]+(:\d+)?$", v):
#             raise ValueError(
#                 "Invalid URL format. Expected format: http://localhost:9000 or https://s3.embl.de"
#             )
#         return v

#     @field_validator("aws_access_key_id")
#     def validate_aws_access_key_id(cls, v):
#         if not v:
#             raise ValueError("AWS access key ID cannot be empty")
#         return v

#     @field_validator("aws_secret_access_key")
#     def validate_aws_secret_access_key(cls, v):
#         if not v:
#             raise ValueError("AWS secret access key cannot be empty")
#         return v

#     @field_validator("use_ssl")
#     def validate_use_ssl(cls, v):
#         if not isinstance(v, str):
#             raise ValueError("use_ssl must be a string")
#         if v.lower() not in ["true", "false"]:
#             raise ValueError("use_ssl must be 'true' or 'false'")
#         return v

#     @field_validator("signature_version")
#     def validate_signature_version(cls, v):
#         if not v:
#             raise ValueError("Signature version cannot be empty")
#         return v

#     @field_validator("region")
#     def validate_region(cls, v):
#         if not v:
#             raise ValueError("Region cannot be empty")
#         return v

#     @field_validator("AWS_ALLOW_HTTP")
#     def validate_AWS_ALLOW_HTTP(cls, v):
#         if not isinstance(v, str):
#             raise ValueError("AWS_ALLOW_HTTP must be a string")
#         if v.lower() not in ["true", "false"]:
#             raise ValueError("AWS_ALLOW_HTTP must be 'true' or 'false'")
#         return v

#     @field_validator("AWS_S3_ALLOW_UNSAFE_RENAME")
#     def validate_AWS_S3_ALLOW_UNSAFE_RENAME(cls, v):
#         if not isinstance(v, str):
#             raise ValueError("AWS_S3_ALLOW_UNSAFE_RENAME must be a string")
#         if v.lower() not in ["true", "false"]:
#             raise ValueError("AWS_S3_ALLOW_UNSAFE_RENAME must be 'true' or 'false'")
#         return v


# def is_minio_running_in_docker():
#     import socket

#     try:
#         # Try to resolve the 'minio' hostname, which will only work
#         # if we're in the same Docker network as the Minio service
#         socket.gethostbyname("minio")
#         return True
#     except socket.gaierror:
#         # If the hostname can't be resolved, we're likely not running in Docker
#         # or Minio isn't present in the network
#         return False


# # DOCS: Document the `is_minio_running_in_docker` function
# class S3DepictioCLIConfig(BaseSettings):
#     """Test-specific version of S3DepictioCLIConfig for isolated testing."""

#     service_name: str = Field(default="minio")
#     host: str = Field(default="localhost")
#     endpoint_url: str = Field(default="http://localhost:9000")
#     port: Optional[int] = Field(default=0)
#     root_user: str = Field(default="minio")
#     root_password: str = Field(default="minio123")
#     bucket: str = Field(default="depictio-bucket")
#     on_premise_service: Optional[bool] = Field(default=None)
#     model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_")

#     @field_validator("on_premise_service", mode="before")
#     def set_on_premise_service_default(cls, v):
#         """Set default value for on_premise_service only if it's None."""
#         logger.debug(f"Setting on_premise_service: {v}")
#         if v is None:
#             return is_minio_running_in_docker()
#         return v

#     @model_validator(mode="after")
#     def update_endpoint_url_based_on_context(cls, model):
#         logger.debug(f"Updating endpoint_url for model: {model}")

#         # First, parse the current endpoint_url to extract information
#         url_parts = urlparse(model.endpoint_url)

#         # Extract host from endpoint_url
#         model.host = url_parts.netloc.split(":")[0]
#         logger.debug(f"Extracted host: {model.host}")

#         # Extract port from netloc if present
#         if ":" in url_parts.netloc:
#             model.port = int(url_parts.netloc.split(":")[1])
#         logger.debug(f"Using port: {model.port}")

#         # Determine secure mode based on the endpoint_url
#         secure = url_parts.scheme == "https"
#         logger.debug(f"Secure mode set to: {secure}")

#         try:
#             logger.debug(f"DEPICTIO_CONTEXT: {DEPICTIO_CONTEXT}")

#             # CASE 1: Server context and on-premise - use service name
#             if DEPICTIO_CONTEXT == "server" and model.on_premise_service:
#                 port = model.port or 9000
#                 new_endpoint = f"http://{model.service_name}:{port}"

#                 # Only update if different
#                 if new_endpoint != model.endpoint_url:
#                     model.endpoint_url = new_endpoint
#                     logger.debug(
#                         f"Updated endpoint_url for server+on-premise: {model.endpoint_url}"
#                     )

#             # CASE 2: Using service name but NOT on-premise or not in server context
#             # This is the case that needs fixing according to the logs
#             elif model.host == model.service_name and not model.on_premise_service:
#                 # We need to revert to using the actual host, not the service name
#                 # Default to localhost if we're not on-premise
#                 actual_host = "localhost"  # Default when not on-premise
#                 port = model.port or 9000

#                 model.endpoint_url = f"{'https' if secure else 'http'}://{actual_host}:{port}"
#                 model.host = actual_host
#                 logger.debug(f"Fixed endpoint_url for non-on-premise: {model.endpoint_url}")

#             # CASE 3: Other cases - rebuild URL if needed
#             else:
#                 # For other contexts, ensure URL is consistent with host/port
#                 new_endpoint = f"{'https' if secure else 'http'}://{model.host}"
#                 new_endpoint += f":{model.port}" if model.port else ""

#                 if new_endpoint != model.endpoint_url:
#                     model.endpoint_url = new_endpoint
#                     logger.debug(f"Standardized endpoint_url: {model.endpoint_url}")

#         except NameError:
#             # DEPICTIO_CONTEXT might not be defined, handle gracefully
#             logger.debug("DEPICTIO_CONTEXT not defined, skipping context-specific adjustments")
#             pass

#         return model


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

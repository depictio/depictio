import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError

import depictio.api.v1.configs.settings_models as settings_models
from depictio.api.v1.configs.settings_models import (
    AuthConfig,
    # Collections,
    FastAPIConfig,
    # JBrowseConfig,
    MongoDBConfig,
    S3CacheConfig,
    S3DepictioCLIConfig,
    Settings,
    ViewerConfig,
)


@contextmanager
def env_vars(env_dict):
    """Context manager for temporarily setting environment variables."""
    original = {key: os.environ.get(key) for key in env_dict}
    try:
        # Set temporary environment variables
        for key, value in env_dict.items():
            if value is not None:
                os.environ[key] = value
            else:
                if key in os.environ:
                    del os.environ[key]
        yield
    finally:
        # Restore original environment
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value
            else:
                if key in os.environ:
                    del os.environ[key]


# class TestCollections:
#     def test_default_values(self):
#         """Test Collections with default values."""
#         collections = Collections()

#         assert collections.projects_collection == "projects"
#         assert collections.data_collection == "data_collections"
#         assert collections.workflow_collection == "workflows"
#         assert collections.runs_collection == "runs"
#         assert collections.files_collection == "files"
#         assert collections.users_collection == "users"
#         assert collections.tokens_collection == "tokens"
#         assert collections.groups_collection == "groups"
#         assert collections.deltatables_collection == "deltatables"
#         assert collections.jbrowse_collection == "jbrowse_collection"
#         assert collections.dashboards_collection == "dashboards"
#         assert collections.initialization_collection == "initialization"
#         assert collections.test_collection == "test"

#     def test_custom_values(self):
#         """Test Collections with custom values."""
#         collections = Collections(
#             projects_collection="custom_projects",
#             data_collection="custom_data",
#             users_collection="custom_users",
#         )

#         assert collections.projects_collection == "custom_projects"
#         assert collections.data_collection == "custom_data"
#         assert collections.users_collection == "custom_users"
#         # Other values should remain default
#         assert collections.workflow_collection == "workflows"


class TestMongoDBConfig:
    def test_default_values(self):
        """Test MongoConfig with default values."""
        env_to_clear = {
            "DEPICTIO_MONGODB_SERVICE_PORT": None,
            "DEPICTIO_MONGODB_EXTERNAL_PORT": None,
            "DEPICTIO_MONGODB_DB_NAME": None,
            "DEPICTIO_MONGODB_WIPE": None,
        }

        with env_vars(env_to_clear):
            config = MongoDBConfig()

            assert isinstance(config.collections, MongoDBConfig.Collections)
            assert config.service_name == "mongo"
            assert config.service_port == 27018
            assert config.external_port == 27018
            assert config.db_name == "depictioDB"
            assert config.wipe is False

    def test_custom_values(self):
        """Test MongoConfig with custom values."""
        env_to_clear = {
            "DEPICTIO_MONGODB_SERVICE_PORT": None,
            "DEPICTIO_MONGODB_EXTERNAL_PORT": None,
            "DEPICTIO_MONGODB_DB_NAME": None,
            "DEPICTIO_MONGODB_WIPE": None,
        }

        with env_vars(env_to_clear):
            config = MongoDBConfig(
                service_name="custom_mongo",
                service_port=12345,
                external_port=12345,
                db_name="custom_db",
                wipe=True,
            )

            assert config.service_name == "custom_mongo"
            assert config.service_port == 12345
            assert config.external_port == 12345
            assert config.db_name == "custom_db"
            assert config.wipe is True

    def test_env_variables(self):
        """Test MongoConfig with environment variables."""
        env = {
            "DEPICTIO_MONGODB_SERVICE_PORT": "54321",
            "DEPICTIO_MONGODB_EXTERNAL_PORT": "54321",
            "DEPICTIO_MONGODB_DB_NAME": "env_db",
            "DEPICTIO_MONGODB_WIPE": "true",
        }

        with env_vars(env):
            config = MongoDBConfig()

            assert config.service_port == 54321
            assert config.external_port == 54321
            assert config.db_name == "env_db"
            assert config.wipe is True


class TestFastAPIConfig:
    def test_default_values(self):
        """Test FastAPIConfig with default values."""
        env_to_clear = {
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": None,
            "DEPICTIO_FASTAPI_LOGGING_LEVEL": None,
            "DEPICTIO_FASTAPI_WORKERS": None,
            "DEPICTIO_FASTAPI_SSL": None,
            # "DEPICTIO_FASTAPI_PLAYWRIGHT_DEV_MODE": None,
        }

        with env_vars(env_to_clear):
            config = FastAPIConfig()

            assert config.host == "0.0.0.0"
            assert config.service_name == "depictio-backend"
            assert config.external_port == 8058
            assert config.logging_level == "INFO"
            assert config.workers == 4
            assert config.ssl is False
            # assert config.playwright_dev_mode is False
            # assert config.internal_api_key is not None  # Generated by default

    def test_custom_values(self):
        """Test FastAPIConfig with custom values."""
        env_to_clear = {
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": None,
            "DEPICTIO_FASTAPI_LOGGING_LEVEL": None,
            "DEPICTIO_FASTAPI_WORKERS": None,
            "DEPICTIO_FASTAPI_SSL": None,
            "DEPICTIO_FASTAPI_PLAYWRIGHT_DEV_MODE": None,
        }

        with env_vars(env_to_clear):
            config = FastAPIConfig(
                host="127.0.0.1",
                service_name="custom_backend",
                service_port=9000,
                external_port=9000,
                logging_level="DEBUG",
                workers=4,
                ssl=True,
                # playwright_dev_mode=True,
                # internal_api_key="custom_key",
            )

            assert config.host == "127.0.0.1"
            assert config.service_name == "custom_backend"
            assert config.external_port == 9000
            assert config.logging_level == "DEBUG"
            assert config.workers == 4
            assert config.ssl is True
            # assert config.playwright_dev_mode is True
            # assert config.internal_api_key == "custom_key"

    def test_env_variables(self):
        """Test FastAPIConfig with environment variables."""
        env = {
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": "7000",
            "DEPICTIO_FASTAPI_LOGGING_LEVEL": "ERROR",
            "DEPICTIO_FASTAPI_WORKERS": "2",
            "DEPICTIO_FASTAPI_SSL": "true",
            # "DEPICTIO_FASTAPI_PLAYWRIGHT_DEV_MODE": "true",
            # "DEPICTIO_FASTAPI_INTERNAL_API_KEY": "env_api_key",
        }

        with env_vars(env):
            config = FastAPIConfig()

            assert config.external_port == 7000
            assert config.logging_level == "ERROR"
            assert config.workers == 2
            assert config.ssl is True
            # assert config.playwright_dev_mode is True
            # assert config.internal_api_key == "env_api_key"


class TestViewerConfig:
    def test_default_values(self):
        """Test ViewerConfig with default values."""
        env_to_clear = {
            "DEPICTIO_VIEWER_DEBUG": None,
            "DEPICTIO_VIEWER_EXTERNAL_PORT": None,
            "DEPICTIO_VIEWER_WORKERS": None,
        }

        with env_vars(env_to_clear):
            config = ViewerConfig()

            assert config.debug is True
            assert config.host == "0.0.0.0"
            assert config.service_name == "depictio-viewer"
            assert config.service_port == 80
            assert config.workers == 4
            assert config.external_port == 5080

    def test_custom_values(self):
        """Test ViewerConfig with custom values."""
        env_to_clear = {
            "DEPICTIO_VIEWER_DEBUG": None,
            "DEPICTIO_VIEWER_EXTERNAL_PORT": None,
            "DEPICTIO_VIEWER_WORKERS": None,
        }

        with env_vars(env_to_clear):
            config = ViewerConfig(
                debug=False,
                host="127.0.0.1",
                service_name="custom_frontend",
                workers=4,
                service_port=3000,
                external_port=3000,
            )

            assert config.debug is False
            assert config.host == "127.0.0.1"
            assert config.service_name == "custom_frontend"
            assert config.workers == 4
            assert config.external_port == 3000

    def test_env_variables(self):
        """Test ViewerConfig with environment variables."""
        env = {
            "DEPICTIO_VIEWER_DEBUG": "false",
            "DEPICTIO_VIEWER_EXTERNAL_PORT": "4000",
            "DEPICTIO_VIEWER_WORKERS": "2",
        }

        with env_vars(env):
            config = ViewerConfig()

            assert config.debug is False
            assert config.external_port == 4000
            assert config.workers == 2

    def test_dashboards_default_view(self):
        """The listing's default view is a deployment setting."""
        with env_vars({"DEPICTIO_VIEWER_DASHBOARDS_DEFAULT_VIEW": None}):
            assert ViewerConfig().dashboards_default_view == "thumbnails"

        with env_vars({"DEPICTIO_VIEWER_DASHBOARDS_DEFAULT_VIEW": "table"}):
            assert ViewerConfig().dashboards_default_view == "table"

    def test_dashboards_default_view_rejects_unknown(self):
        """A typo must fail at startup rather than reach the SPA."""
        with env_vars({"DEPICTIO_VIEWER_DASHBOARDS_DEFAULT_VIEW": "tiles"}):
            with pytest.raises(ValidationError):
                ViewerConfig()


# class TestJBrowseConfig:
#     def test_default_values(self):
#         """Test JBrowseConfig with default values."""
#         env_to_clear = {
#             "DEPICTIO_JBROWSE_ENABLED": None,
#             "DEPICTIO_JBROWSE_DATA_DIR": None,
#             "DEPICTIO_JBROWSE_CONFIG_DIR": None,
#         }

#         with env_vars(env_to_clear):
#             config = JBrowseConfig()

#             assert config.enabled is True
#             assert config.instance == {"host": "http://localhost", "port": 3000}
#             assert config.watcher_plugin == {"host": "http://localhost", "port": 9010}
#             assert config.data_dir == "/data"
#             assert config.config_dir == "/jbrowse-watcher-plugin/sessions"

#     def test_custom_values(self):
#         """Test JBrowseConfig with custom values."""
#         env_to_clear = {
#             "DEPICTIO_JBROWSE_ENABLED": None,
#             "DEPICTIO_JBROWSE_DATA_DIR": None,
#             "DEPICTIO_JBROWSE_CONFIG_DIR": None,
#         }

#         with env_vars(env_to_clear):
#             config = JBrowseConfig(
#                 enabled=False,
#                 instance={"host": "http://jbrowse", "port": 4000},
#                 data_dir="/custom/data",
#                 config_dir="/custom/config",
#             )

#             assert config.enabled is False
#             assert config.instance == {"host": "http://jbrowse", "port": 4000}
#             assert config.data_dir == "/custom/data"
#             assert config.config_dir == "/custom/config"

#     def test_env_variables(self):
#         """Test JBrowseConfig with environment variables."""
#         env = {
#             "DEPICTIO_JBROWSE_ENABLED": "false",
#             "DEPICTIO_JBROWSE_DATA_DIR": "/env/data",
#             "DEPICTIO_JBROWSE_CONFIG_DIR": "/env/config",
#         }

#         with env_vars(env):
#             config = JBrowseConfig()

#             assert config.enabled is False
#             assert config.data_dir == "/env/data"
#             assert config.config_dir == "/env/config"


class TestAuthConfig:
    def test_default_values(self):
        """Test Auth with default values."""
        env_to_clear = {
            "DEPICTIO_AUTH_KEYS_DIR": None,
            "DEPICTIO_AUTH_KEYS_ALGORITHM": None,
            "DEPICTIO_AUTH_CLI_CONFIG_DIR": None,
            "DEPICTIO_AUTH_INTERNAL_API_KEY": None,
        }

        with env_vars(env_to_clear):
            config = AuthConfig()

            # The keys_dir and cli_config_dir now use absolute paths based on the package location
            assert config.keys_dir.name == "keys"
            assert config.keys_dir.parent.name == "depictio"
            assert config.keys_algorithm == "RS256"
            assert config.cli_config_dir.name == ".depictio"
            assert config.cli_config_dir.parent.name == "depictio"
            # internal_api_key is now computed and always returns a value (either from env or generated)
            assert config.internal_api_key is not None
            assert isinstance(config.internal_api_key, str)
            assert len(config.internal_api_key) > 0

    def test_custom_values(self):
        """Test Auth with custom values."""
        env_to_clear = {
            "DEPICTIO_AUTH_KEYS_DIR": None,
            "DEPICTIO_AUTH_KEYS_ALGORITHM": None,
            "DEPICTIO_AUTH_CLI_CONFIG_DIR": None,
            "DEPICTIO_AUTH_INTERNAL_API_KEY": None,
        }

        # Create a temporary directory path or use a project-relative path
        import tempfile

        temp_dir = tempfile.mkdtemp()
        custom_keys_dir = f"{temp_dir}/custom/keys"
        custom_config_dir = f"{temp_dir}/custom/config"

        try:
            with env_vars(env_to_clear):
                config = AuthConfig(
                    keys_dir=custom_keys_dir,
                    keys_algorithm="RS256",
                    cli_config_dir=custom_config_dir,
                    internal_api_key_env="custom_api_key",
                )

                assert config.keys_dir == Path(custom_keys_dir)
                assert config.keys_algorithm == "RS256"
                assert config.cli_config_dir == Path(custom_config_dir)
                assert config.internal_api_key_env == "custom_api_key"
                # Test that the computed property returns the custom value
                assert config.internal_api_key == "custom_api_key"
        finally:
            # Clean up the temporary directory
            import shutil

            shutil.rmtree(temp_dir)

    def test_env_variables(self):
        """Test Auth with environment variables."""
        # Create temporary directories that are writable
        import os
        import tempfile

        temp_dir = tempfile.mkdtemp()
        env_keys_dir = os.path.join(temp_dir, "env/keys")
        env_config_dir = os.path.join(temp_dir, "env/config")

        try:
            env = {
                "DEPICTIO_AUTH_KEYS_DIR": env_keys_dir,
                "DEPICTIO_AUTH_KEYS_ALGORITHM": "ES256",
                "DEPICTIO_AUTH_CLI_CONFIG_DIR": env_config_dir,
                "DEPICTIO_AUTH_INTERNAL_API_KEY": "env_api_key",
            }

            with env_vars(env):
                config = AuthConfig()

                assert config.keys_dir == Path(env_keys_dir)
                assert config.keys_algorithm == "ES256"
                assert config.cli_config_dir == Path(env_config_dir)
                assert config.internal_api_key_env == "env_api_key"
                # Test that the computed property returns the environment value
                assert config.internal_api_key == "env_api_key"
        finally:
            # Clean up
            import shutil

            shutil.rmtree(temp_dir)


class TestSettings:
    def test_default_values(self):
        """Test Settings with default values."""
        env_to_clear = {
            # Clear all relevant environment variables
            "DEPICTIO_MONGODB_SERVICE_PORT": None,
            "DEPICTIO_MONGODB_EXTERNAL_PORT": None,
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": None,
            "DEPICTIO_VIEWER_EXTERNAL_PORT": None,
            "DEPICTIO_S3_PUBLIC_URL": None,
            # "DEPICTIO_JBROWSE_ENABLED": None,
            "DEPICTIO_AUTH_INTERNAL_API_KEY": None,
        }

        with env_vars(env_to_clear):
            settings = Settings()

            assert isinstance(settings.mongodb, MongoDBConfig)
            assert isinstance(settings.fastapi, FastAPIConfig)
            assert isinstance(settings.viewer, ViewerConfig)
            assert isinstance(settings.s3, S3DepictioCLIConfig)
            # assert isinstance(settings.jbrowse, JBrowseConfig)
            assert isinstance(settings.auth, AuthConfig)

            # Check a few representative values
            assert settings.mongodb.external_port == 27018
            assert settings.fastapi.external_port == 8058
            assert settings.viewer.external_port == 5080
            # assert settings.jbrowse.enabled is True

    def test_custom_values(self):
        """Test Settings with custom values."""
        env_to_clear = {
            # Clear all relevant environment variables
            "DEPICTIO_MONGODB_SERVICE_PORT": None,
            "DEPICTIO_MONGODB_EXTERNAL_PORT": None,
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": None,
            "DEPICTIO_VIEWER_EXTERNAL_PORT": None,
            "DEPICTIO_S3_PUBLIC_URL": None,
            "DEPICTIO_JBROWSE_ENABLED": None,
            "DEPICTIO_AUTH_INTERNAL_API_KEY": None,
        }

        with env_vars(env_to_clear):
            # Create custom configs
            mongo_config = MongoDBConfig(service_port=12345, external_port=12345)
            fastapi_config = FastAPIConfig(service_port=9000, external_port=9000)
            viewer_config = ViewerConfig(service_port=4000, external_port=4000)
            s3_config = S3DepictioCLIConfig(public_url="https://custom-s3.example.com")
            # jbrowse_config = JBrowseConfig(enabled=False)
            auth_config = AuthConfig()

            settings = Settings(
                mongodb=mongo_config,
                fastapi=fastapi_config,
                viewer=viewer_config,
                s3=s3_config,
                # jbrowse=jbrowse_config,
                auth=auth_config,
            )

            assert settings.mongodb.external_port == 12345
            assert settings.fastapi.external_port == 9000
            assert settings.viewer.external_port == 4000
            assert settings.s3.public_url == "https://custom-s3.example.com"
            # assert settings.jbrowse.enabled is False
            assert isinstance(settings.auth, AuthConfig)

    def test_env_variables(self):
        """Test Settings with environment variables."""
        env = {
            "DEPICTIO_MONGODB_SERVICE_PORT": "54321",
            "DEPICTIO_MONGODB_EXTERNAL_PORT": "54321",
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": "7000",
            "DEPICTIO_VIEWER_EXTERNAL_PORT": "6000",
            "DEPICTIO_S3_PUBLIC_URL": "https://env-s3.example.com",
            "DEPICTIO_FASTAPI_PUBLIC_URL": "https://env-fastapi.example.com",
            "DEPICTIO_JBROWSE_ENABLED": "false",
            "DEPICTIO_AUTH_INTERNAL_API_KEY": "env_token",
        }

        with env_vars(env):
            # Instead of using the composite Settings class, test each component individually
            # to ensure each one is initialized with the current environment variables
            mongodb = MongoDBConfig()
            fastapi = FastAPIConfig()
            viewer = ViewerConfig()
            s3 = S3DepictioCLIConfig()
            # jbrowse = JBrowseConfig()
            auth = AuthConfig()

            assert mongodb.external_port == 54321
            assert fastapi.external_port == 7000
            assert viewer.external_port == 6000
            assert s3.public_url == "https://env-s3.example.com"
            # assert jbrowse.enabled is False
            assert auth.internal_api_key_env == "env_token"

            # Create Settings instance explicitly with our configs
            settings = Settings(
                mongodb=mongodb,
                fastapi=fastapi,
                viewer=viewer,
                s3=s3,
                # jbrowse=jbrowse,
                auth=auth,
            )

            # Verify settings contains our configs
            assert settings.mongodb.external_port == 54321
            assert settings.fastapi.external_port == 7000
            assert settings.viewer.external_port == 6000
            assert settings.s3.public_url == "https://env-s3.example.com"
            assert settings.fastapi.public_url == "https://env-fastapi.example.com"
            # assert settings.jbrowse.enabled is False
            assert settings.auth.internal_api_key_env == "env_token"

    def test_unauthenticated_mode_configuration(self):
        """Test Settings with unauthenticated mode configuration."""
        env = {
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE": "true",
            "DEPICTIO_AUTH_ANONYMOUS_USER_EMAIL": "test_anon@example.com",
        }

        with env_vars(env):
            settings = Settings()

            assert settings.auth.unauthenticated_mode is True
            assert settings.auth.anonymous_user_email == "test_anon@example.com"

    def test_unauthenticated_mode_defaults(self):
        """Test Settings default values for unauthenticated mode."""
        env_to_clear = {
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE": None,
            "DEPICTIO_AUTH_ANONYMOUS_USER_EMAIL": None,
        }

        with env_vars(env_to_clear):
            settings = Settings()

            assert settings.auth.unauthenticated_mode is False
            assert settings.auth.anonymous_user_email == "anonymous@depict.io"


class TestS3ConfigLegacyEnv:
    """DEPICTIO_S3_* is the canonical prefix; DEPICTIO_MINIO_* stays a fallback."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in list(os.environ):
            if key.upper().startswith(("DEPICTIO_S3_", "DEPICTIO_MINIO_")):
                monkeypatch.delenv(key)
        monkeypatch.setattr(settings_models, "_legacy_s3_env_warned", False)

    def test_new_env_only(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        monkeypatch.setenv("DEPICTIO_S3_ROOT_PASSWORD", "new-secret")
        cfg = S3DepictioCLIConfig()
        assert cfg.bucket == "new-bucket"
        assert cfg.aws_secret_access_key == "new-secret"

    def test_legacy_env_only(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_MINIO_BUCKET", "legacy-bucket")
        monkeypatch.setenv("DEPICTIO_MINIO_ROOT_USER", "legacy-user")
        monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", "legacy-secret")
        monkeypatch.setenv("DEPICTIO_MINIO_PUBLIC_URL", "https://legacy.example.com")
        monkeypatch.setenv("DEPICTIO_MINIO_EXTERNAL_SERVICE", "true")
        cfg = S3DepictioCLIConfig()
        assert cfg.bucket == "legacy-bucket"
        assert cfg.aws_access_key_id == "legacy-user"
        assert cfg.aws_secret_access_key == "legacy-secret"
        assert cfg.public_url == "https://legacy.example.com"
        assert cfg.external_service is True

    def test_new_env_wins_over_legacy(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        monkeypatch.setenv("DEPICTIO_MINIO_BUCKET", "legacy-bucket")
        monkeypatch.setenv("DEPICTIO_MINIO_SERVICE_NAME", "legacy-host")
        cfg = S3DepictioCLIConfig()
        assert cfg.bucket == "new-bucket"
        # Fields only set under the legacy name still come through.
        assert cfg.service_name == "legacy-host"

    def test_field_name_kwargs_win_over_env(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        monkeypatch.setenv("DEPICTIO_MINIO_BUCKET", "legacy-bucket")
        cfg = S3DepictioCLIConfig(bucket="kwarg-bucket", root_password="kwarg-secret")
        assert cfg.bucket == "kwarg-bucket"
        assert cfg.aws_secret_access_key == "kwarg-secret"

    def test_default_service_name_is_s3(self):
        assert S3DepictioCLIConfig().service_name == "s3"

    def test_deprecation_warning_lists_legacy_vars(self, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(settings_models, "_warn", messages.append)
        monkeypatch.setenv("DEPICTIO_MINIO_BUCKET", "legacy-bucket")
        monkeypatch.setenv("DEPICTIO_MINIO_ROOT_USER", "legacy-user")
        S3DepictioCLIConfig()
        S3DepictioCLIConfig()
        assert len(messages) == 1
        assert "DEPICTIO_MINIO_BUCKET" in messages[0]
        assert "DEPICTIO_MINIO_ROOT_USER" in messages[0]
        assert "DEPICTIO_S3_" in messages[0]

    def test_no_warning_without_legacy_vars(self, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(settings_models, "_warn", messages.append)
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        S3DepictioCLIConfig()
        assert messages == []

    def test_cache_dir_env_is_independent(self, monkeypatch):
        """DEPICTIO_S3_CACHE_DIR belongs to S3CacheConfig and must not break storage."""
        monkeypatch.setenv("DEPICTIO_S3_CACHE_DIR", "/data/s3-cache")
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        assert S3CacheConfig().cache_dir == "/data/s3-cache"
        cfg = S3DepictioCLIConfig()
        assert cfg.bucket == "new-bucket"
        assert not hasattr(cfg, "cache_dir")

    def test_settings_minio_alias_returns_s3(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_S3_BUCKET", "new-bucket")
        settings = Settings(context="client")
        assert settings.minio is settings.s3
        assert settings.minio.bucket == "new-bucket"

    def test_yaml_dict_by_field_name(self, monkeypatch):
        """CLI YAML ``s3_storage`` dicts keep using plain field names."""
        from depictio.models.models.cli import CLIConfig

        monkeypatch.setenv("DEPICTIO_MINIO_BUCKET", "legacy-bucket")
        config = CLIConfig.model_validate(
            {
                "api_base_url": "http://localhost:8058",
                "user": {
                    "email": "user@example.com",
                    "is_admin": False,
                    "token": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "access_token": "token",
                        "refresh_token": "refresh",
                        "token_type": "bearer",
                        "token_lifetime": "short-lived",
                        "expire_datetime": "2025-12-31T23:59:59",
                        "refresh_expire_datetime": "2025-12-31T23:59:59",
                        "name": "test_token",
                        "created_at": "2025-06-30T18:00:00",
                        "logged_in": False,
                    },
                },
                "s3_storage": {
                    "service_name": "storage",
                    "external_host": "s3.example.com",
                    "root_user": "yaml-user",
                    "root_password": "yaml-secret",
                    "bucket": "yaml-bucket",
                },
            }
        )
        assert config.s3_storage.bucket == "yaml-bucket"
        assert config.s3_storage.service_name == "storage"
        assert config.s3_storage.aws_secret_access_key == "yaml-secret"

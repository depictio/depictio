import copy
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError
from typer import Exit

# Remove this line as we already import datetime later
from depictio.cli.cli.utils.common import (
    _apply_env_overrides,
    cli_config_file,
    describe_api_target,
    format_timestamp,
    generate_api_headers,
    load_depictio_config,
    validate_depictio_cli_config,
)
from depictio.models.models.cli import CLIConfig


class TestCommon:
    """Test suite for common utility functions"""

    @pytest.fixture
    def sample_cli_config(self):
        """Sample CLI configuration dictionary"""
        return {
            "user": {
                "email": "test@example.com",
                "is_admin": False,
                "id": "507f1f77bcf86cd799439011",
                "token": {
                    "user_id": "507f1f77bcf86cd799439011",
                    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l",
                    "refresh_token": "refresh-token-example",
                    "token_type": "bearer",
                    "token_lifetime": "short-lived",
                    "expire_datetime": "2025-12-31T23:59:59",
                    "refresh_expire_datetime": "2025-12-31T23:59:59",
                    "name": "test_token",
                    "created_at": "2025-06-30T18:00:00",
                    "logged_in": False,
                },
            },
            "api_base_url": "https://api.depictio.dev",
            "s3_storage": {
                "service_name": "minio",
                "service_port": 9000,
                "external_host": "localhost",
                "external_port": 9000,
                "external_protocol": "http",
                "root_user": "minio",
                "root_password": "minio123",
                "bucket": "depictio-bucket",
            },
        }

    @pytest.fixture
    def sample_cli_config_object(self, sample_cli_config):
        """Sample CLI configuration as a CLIConfig object"""
        return CLIConfig(**sample_cli_config)  # type: ignore[missing-argument]

    class TestGenerateApiHeaders:
        """Tests for generate_api_headers function"""

        def test_with_dict(self, sample_cli_config):
            """Test generate_api_headers with dictionary input.

            Besides the bearer token, every request now carries the CLI instance
            identity (hostname always; label only when set in the config) so the
            server's monitoring can distinguish multiple CLIs.
            """
            import socket

            expected_token = f"Bearer {sample_cli_config['user']['token']['access_token']}"
            headers = generate_api_headers(sample_cli_config)
            assert headers["Authorization"] == expected_token
            assert headers["X-Depictio-CLI-Host"] == socket.gethostname()
            # No instance_label in the sample config → header omitted.
            assert "X-Depictio-CLI-Instance" not in headers

        def test_with_object(self, sample_cli_config, sample_cli_config_object):
            """Test generate_api_headers with CLIConfig object input"""
            import socket

            expected_token = f"Bearer {sample_cli_config['user']['token']['access_token']}"
            headers = generate_api_headers(sample_cli_config_object)
            assert headers["Authorization"] == expected_token
            assert headers["X-Depictio-CLI-Host"] == socket.gethostname()

        def test_includes_instance_label_when_set(self, sample_cli_config):
            """When instance_label is set in the CLI config, it is sent as a header."""
            sample_cli_config["instance_label"] = "lab-workstation-1"
            headers = generate_api_headers(sample_cli_config)
            assert headers["X-Depictio-CLI-Instance"] == "lab-workstation-1"

        def test_with_invalid_input(self):
            """Test generate_api_headers with invalid input type"""
            with pytest.raises(ValidationError):
                generate_api_headers("not_a_dict_or_object")

        def test_with_empty_input(self):
            """Test generate_api_headers with empty input"""
            with pytest.raises(ValueError):
                generate_api_headers(None)

    class TestFormatTimestamp:
        """Tests for format_timestamp function"""

        def test_valid_timestamp(self):
            """Test format_timestamp with a valid timestamp"""
            # Using a fixed timestamp (2023-01-01 12:00:00)
            timestamp = 1672574400.0
            formatted = format_timestamp(timestamp)
            # Instead of hardcoding the expected time, calculate it based on the same method
            expected = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            assert formatted == expected

        def test_invalid_timestamp(self):
            """Test format_timestamp with an invalid timestamp"""
            # Using an invalid timestamp
            with pytest.raises(ValidationError):
                format_timestamp("not_a_timestamp")

    class TestValidateDepictioCliConfig:
        """Tests for validate_depictio_cli_config function"""

        def test_valid_config(self, sample_cli_config):
            """Test validate_depictio_cli_config with valid config"""
            with patch("depictio.cli.cli.utils.common.logger"):
                result = validate_depictio_cli_config(sample_cli_config)
                assert isinstance(result, CLIConfig)
                config_dict = result.model_dump()
                assert (
                    config_dict["user"]["token"]["access_token"]
                    == "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l"
                )
                assert config_dict["api_base_url"] == "https://api.depictio.dev"
                assert config_dict["s3_storage"]["bucket"] == "depictio-bucket"

        def test_invalid_config(self):
            """Test validate_depictio_cli_config with invalid config"""
            with pytest.raises(Exception):
                validate_depictio_cli_config({"invalid": "config"})

    class TestLoadDepictioConfig:
        """Tests for load_depictio_config function"""

        def test_success(self):
            """Test successful loading of config file"""
            mock_config = {
                "user": {
                    "email": "test@example.com",
                    "is_admin": False,
                    "id": "507f1f77bcf86cd799439011",
                    "token": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWV9.EkN-DOsnsuRjRO6BxXemmJDm3HbxrbRzXglbN2S4sOkopdU4IsDxTI8jO19W_A4K8ZPJijNLis4EZsHeY559a4DFOd50_OqgHs3O2GWl5JQ6TyYHdMKoGNAHnm8l",
                        "refresh_token": "refresh-token-example",
                        "token_type": "bearer",
                        "token_lifetime": "short-lived",
                        "expire_datetime": "2025-12-31T23:59:59",
                        "refresh_expire_datetime": "2025-12-31T23:59:59",
                        "name": "test_token",
                        "created_at": "2025-06-30T18:00:00",
                        "logged_in": False,
                    },
                },
                "api_base_url": "https://api.depictio.dev",
                "s3_storage": {
                    "service_name": "minio",
                    "service_port": 9000,
                    "external_host": "localhost",
                    "external_port": 9000,
                    "external_protocol": "http",
                    "root_user": "minio",
                    "root_password": "minio123",
                    "bucket": "depictio-bucket",
                },
            }

            # Mock the get_config and validate_depictio_cli_config functions
            with (
                patch("depictio.cli.cli.utils.common.get_config") as mock_get_config,
                patch(
                    "depictio.cli.cli.utils.common.validate_depictio_cli_config"
                ) as mock_validate,
                patch("depictio.cli.cli.utils.common.rich_print_checked_statement"),
            ):
                mock_get_config.return_value = mock_config
                mock_validate.return_value = CLIConfig(
                    api_base_url=mock_config["api_base_url"],
                    user=mock_config["user"],
                    s3_storage=mock_config["s3_storage"],
                )

                # A real file on disk: load_depictio_config checks the path
                # exists before reading it, and the default ~/.depictio/CLI.yaml
                # is present on a developer machine but not on CI.
                with tempfile.TemporaryDirectory() as tmp_dir:
                    config_path = os.path.join(tmp_dir, "CLI.yaml")
                    with open(config_path, "w") as handle:
                        handle.write("placeholder: true\n")
                    result = load_depictio_config(yaml_config_path=config_path)

                # Verify that the functions were called
                mock_get_config.assert_called_once()
                mock_validate.assert_called_once_with(mock_config)

                # Verify the result
                assert isinstance(result, CLIConfig)

        def test_file_not_found(self):
            """Test load_depictio_config when file is not found"""
            # Mock the get_config function to raise FileNotFoundError
            with (
                patch("depictio.cli.cli.utils.common.get_config") as mock_get_config,
                patch("depictio.cli.cli.utils.common.rich_print_checked_statement"),
                patch("depictio.cli.cli.utils.common.logger"),
            ):
                mock_get_config.side_effect = FileNotFoundError()

                with pytest.raises(Exit):
                    load_depictio_config()

    class TestEnvironmentOverrides:
        """Tests for the DEPICTIO_CLI_* environment overrides.

        These let a ``CLI.yaml`` be committed without secrets and have the token
        (and optionally the API URL / the config path itself) injected at runtime,
        which is what makes automated triggering practical: the head job of a
        pipeline usually has env vars but no writable home directory.

        Every test here works against a throwaway YAML under ``tmp_path`` — the
        real ``~/.depictio`` is never read or written.
        """

        _ENV_VARS = (
            "DEPICTIO_CLI_TOKEN",
            "DEPICTIO_CLI_API_BASE_URL",
            "DEPICTIO_CLI_CONFIG_PATH",
        )

        @pytest.fixture(autouse=True)
        def isolated_env(self, monkeypatch):
            """Start from a clean slate so a developer's shell can't taint results."""
            for var in self._ENV_VARS:
                monkeypatch.delenv(var, raising=False)
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement"):
                yield

        def _write_config(self, tmp_path, sample_cli_config, filename, api_base_url):
            """Write a valid CLI config YAML, tagged by its api_base_url.

            The URL doubles as a marker: asserting on it tells us *which* file a
            given call actually loaded.
            """
            config = copy.deepcopy(sample_cli_config)
            config["api_base_url"] = api_base_url
            path = tmp_path / filename
            path.write_text(yaml.safe_dump(config))
            return path

        @pytest.fixture
        def config_file(self, tmp_path, sample_cli_config):
            """A throwaway CLI config file (never ``~/.depictio``)."""
            return self._write_config(
                tmp_path, sample_cli_config, "CLI.yaml", "https://from-env-path.example.org"
            )

        def test_token_env_var_overrides_config(self, monkeypatch, config_file):
            """DEPICTIO_CLI_TOKEN replaces the access token from the YAML."""
            monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "env.injected.token")

            config = load_depictio_config(str(config_file))

            assert config.user.token.access_token == "env.injected.token"

        def test_token_env_var_when_user_key_missing(self, monkeypatch):
            """A secret-free config need not carry a ``user`` key at all."""
            monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "env.injected.token")

            result = _apply_env_overrides({"api_base_url": "https://api.depictio.dev"})

            assert result["user"]["token"]["access_token"] == "env.injected.token"

        @pytest.mark.parametrize("token_value", [None, "not-a-dict", 42, ["list"]])
        def test_token_env_var_when_token_is_not_a_dict(self, monkeypatch, token_value):
            """A non-dict ``user.token`` is replaced, not indexed into."""
            monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "env.injected.token")

            result = _apply_env_overrides({"user": {"email": "a@b.co", "token": token_value}})

            assert result["user"]["token"] == {"access_token": "env.injected.token"}
            # Other user fields survive the token replacement.
            assert result["user"]["email"] == "a@b.co"

        def test_api_base_url_env_var_overrides_config(self, monkeypatch, config_file):
            """DEPICTIO_CLI_API_BASE_URL replaces the api_base_url from the YAML."""
            monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://depictio.example.org:8058")

            config = load_depictio_config(str(config_file))

            assert config.api_base_url == "https://depictio.example.org:8058"

        def test_no_env_vars_leaves_config_untouched(self, sample_cli_config):
            """With neither variable set, the dict comes back unchanged."""
            original = copy.deepcopy(sample_cli_config)

            result = _apply_env_overrides(sample_cli_config)

            assert result == original

        def test_config_path_env_var_used_without_argument(self, monkeypatch, config_file):
            """DEPICTIO_CLI_CONFIG_PATH selects the file when no path is passed."""
            monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config_file))

            config = load_depictio_config()

            assert config.api_base_url == "https://from-env-path.example.org"

        @pytest.mark.parametrize("default_path", ["~/.depictio/cli.yaml", "~/.depictio/CLI.yaml"])
        def test_config_path_env_var_used_for_default_spellings(
            self, monkeypatch, config_file, default_path
        ):
            """Both historic default spellings are still treated as "no choice made"."""
            monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config_file))

            config = load_depictio_config(default_path)

            assert config.api_base_url == "https://from-env-path.example.org"

        def test_explicit_path_beats_config_path_env_var(
            self, monkeypatch, tmp_path, sample_cli_config, config_file
        ):
            """An explicit --server is never clobbered by the env var."""
            explicit = self._write_config(
                tmp_path, sample_cli_config, "explicit.yaml", "https://from-explicit.example.org"
            )
            monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config_file))

            config = load_depictio_config(str(explicit))

            assert config.api_base_url == "https://from-explicit.example.org"

    class TestWhichFileIsRead:
        """The file a command reads, and how a missing one is reported.

        HOME points at ``tmp_path``, so the developer's ``~/.depictio`` is never read.
        """

        @pytest.fixture(autouse=True)
        def isolated_home(self, monkeypatch, tmp_path):
            monkeypatch.setenv("HOME", str(tmp_path))
            monkeypatch.delenv("DEPICTIO_CLI_CONFIG_PATH", raising=False)
            monkeypatch.delenv("DEPICTIO_CLI_API_BASE_URL", raising=False)

        @pytest.fixture
        def env_config(self, monkeypatch, tmp_path, sample_cli_config):
            config = copy.deepcopy(sample_cli_config)
            config["api_base_url"] = "https://from-env.example.org"
            path = tmp_path / "elsewhere" / "CLI.yaml"
            path.parent.mkdir()
            path.write_text(yaml.safe_dump(config))
            monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(path))
            return path

        def test_the_env_var_stands_in_for_the_default_only(self, env_config):
            assert cli_config_file() == str(env_config)
            assert cli_config_file("other.yaml") == "other.yaml"

        def test_the_default_is_expanded(self, tmp_path):
            assert cli_config_file() == str(tmp_path / ".depictio" / "CLI.yaml")

        def test_a_missing_default_is_not_blamed_on_server(self):
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
                with pytest.raises(Exit):
                    load_depictio_config()

            message = str(printer.call_args)
            assert "(the default)" in message
            assert "pass --server" in message

        def test_a_missing_explicit_file_is_blamed_on_server(self, tmp_path):
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
                with pytest.raises(Exit):
                    load_depictio_config(str(tmp_path / "typo.yaml"))

            assert "(from --server)" in str(printer.call_args)

        def test_describe_api_target_names_the_file_the_env_var_chose(self, env_config):
            described = describe_api_target("~/.depictio/CLI.yaml")

            # HOME is tmp_path here, so the file shows under ~ like the commands take it.
            assert described == "https://from-env.example.org, read from ~/elsewhere/CLI.yaml"

    class TestQuietSuppressesTheLoadingLine:
        """``quiet=True`` loads the same config without announcing it.

        Callers that re-read an already-loaded config only to name a field —
        the API URL in the "server unreachable" error, the viewer URL in the
        run summary — would otherwise print a second "Loading Depictio
        configuration..." in the middle of reporting a failure, implying a
        load that never happened.
        """

        @pytest.fixture
        def config_file(self, tmp_path, sample_cli_config):
            config = copy.deepcopy(sample_cli_config)
            config["api_base_url"] = "https://quiet.example.org"
            path = tmp_path / "CLI.yaml"
            path.write_text(yaml.safe_dump(config))
            return path

        def test_quiet_prints_nothing(self, config_file):
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
                config = load_depictio_config(str(config_file), quiet=True)

            assert config.api_base_url == "https://quiet.example.org"
            assert printer.call_args_list == []

        def test_a_reload_does_not_announce_the_server_again(self, config_file):
            """Login and every step reload the configuration; the command says it once."""
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
                load_depictio_config(str(config_file))
                load_depictio_config(str(config_file))

            announced = [c for c in printer.call_args_list if "Server:" in str(c)]
            assert len(announced) == 1

        def test_default_announces_the_target_server(self, config_file):
            """The flag is opt-in: by default the command says which server it uses."""
            with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
                load_depictio_config(str(config_file))

            assert any(
                "Server: https://quiet.example.org" in str(call) and str(config_file) in str(call)
                for call in printer.call_args_list
            )

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

        def test_file_not_found(self, tmp_path, monkeypatch):
            """Test load_depictio_config when file is not found"""
            # Which default file is read depends on what HOME holds: not the developer's.
            monkeypatch.setenv("HOME", str(tmp_path))
            monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
            monkeypatch.delenv("DEPICTIO_CLI_CONFIG_PATH", raising=False)
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
        def isolated_env(self, monkeypatch, tmp_path):
            """Start from a clean slate so a developer's shell can't taint results."""
            for var in self._ENV_VARS:
                monkeypatch.delenv(var, raising=False)
            # A default target looks for a running local server: not the developer's.
            monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
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
            monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
            monkeypatch.delenv("DEPICTIO_CLI_CONFIG_PATH", raising=False)
            monkeypatch.delenv("DEPICTIO_CLI_API_BASE_URL", raising=False)
            monkeypatch.delenv("DEPICTIO_CLI_TOKEN", raising=False)

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
            default = tmp_path / ".depictio" / "CLI.yaml"
            default.parent.mkdir()
            default.write_text("{}")

            assert cli_config_file() == str(default)

        def test_without_the_default_the_local_server_is_read(self, tmp_path):
            assert cli_config_file() == str(tmp_path / "local" / "cli" / "admin_config.yaml")

        def test_a_missing_default_is_not_blamed_on_server(self, monkeypatch):
            """Missing while a remote server variable is set: no local fallback then."""
            monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")
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


def _valid_config(api_base_url: str = "http://127.0.0.1:8058") -> dict:
    """A loadable CLI configuration whose api_base_url marks which file was read."""
    return {
        "api_base_url": api_base_url,
        "user": {
            "email": "admin@example.com",
            "is_admin": True,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "secret-access-token",
                "refresh_token": "secret-refresh-token",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2099-12-31T23:59:59",
                "refresh_expire_datetime": "2099-12-31T23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        "s3_storage": {
            "service_name": "localhost",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "depictio",
            "root_password": "s3-password",
            "bucket": "depictio-bucket",
        },
    }


class TestConfigurationProblems:
    """What a configuration that cannot be used is reported as: the file, and what is wrong.

    HOME and the local home point under ``tmp_path``: no real configuration is read.
    """

    @pytest.fixture(autouse=True)
    def isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def printed(self):
        """The status lines load_depictio_config prints, on one line each."""
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            yield lambda: [" ".join(str(call.args[0]).split()) for call in printer.call_args_list]

    def _fails_with(self, printed, path: str, **kwargs) -> str:
        with pytest.raises(Exit) as caught:
            load_depictio_config(path, **kwargs)
        assert caught.value.exit_code == 1
        (message,) = printed()
        return message

    def test_broken_yaml_names_the_file(self, tmp_path, printed):
        config = tmp_path / "broken.yaml"
        config.write_text("api_base_url: [unclosed\n")

        assert f"{config} is not valid YAML" in self._fails_with(printed, str(config))

    def test_a_directory_is_reported_as_one(self, tmp_path, printed):
        message = self._fails_with(printed, str(tmp_path))

        assert f"{tmp_path} is a directory, not a Depictio CLI configuration file" in message
        assert "not found" not in message

    def test_a_missing_user_key_is_named(self, tmp_path, printed):
        config = tmp_path / "CLI.yaml"
        config.write_text(yaml.safe_dump({"api_base_url": "http://x.test"}))

        assert "has no 'user' key" in self._fails_with(printed, str(config))

    def test_an_invalid_field_is_named(self, tmp_path, printed):
        broken = _valid_config()
        broken["api_base_url"] = "not-a-url"
        config = tmp_path / "CLI.yaml"
        config.write_text(yaml.safe_dump(broken))

        message = self._fails_with(printed, str(config))
        assert "is not a valid Depictio CLI configuration: api_base_url:" in message

    def test_a_yml_file_is_read(self, tmp_path, printed):
        config = tmp_path / "CLI.yml"
        config.write_text(yaml.safe_dump(_valid_config("http://from-yml.test")))

        assert load_depictio_config(str(config)).api_base_url == "http://from-yml.test"

    def test_the_env_var_takes_local(self, tmp_path, monkeypatch, printed):
        local = tmp_path / "local" / "cli" / "admin_config.yaml"
        local.parent.mkdir(parents=True)
        local.write_text(yaml.safe_dump(_valid_config("http://local.test")))
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", "local")

        assert load_depictio_config().api_base_url == "http://local.test"

    def test_the_env_var_local_without_a_local_server(self, monkeypatch, printed):
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", "LOCAL")

        message = self._fails_with(printed, "~/.depictio/CLI.yaml")
        assert "No local server configuration at" in message
        assert "(from DEPICTIO_CLI_CONFIG_PATH)" in message
        assert "depictio local up" in message

    def test_the_default_file_named_on_purpose_beats_the_env_var(self, tmp_path, monkeypatch):
        from depictio.cli.cli.utils.server_target import resolve_server

        default = tmp_path / "home" / ".depictio" / "CLI.yaml"
        default.parent.mkdir(parents=True)
        default.write_text(yaml.safe_dump(_valid_config("http://named.test")))
        elsewhere = tmp_path / "env.yaml"
        elsewhere.write_text(yaml.safe_dump(_valid_config("http://from-env.test")))
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(elsewhere))

        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            named = load_depictio_config(resolve_server("~/.depictio/CLI.yaml"))
            implicit = load_depictio_config(resolve_server(None))

        assert named.api_base_url == "http://named.test"
        assert implicit.api_base_url == "http://from-env.test"
        # Still shown the way it was typed.
        assert "configuration ~/.depictio/CLI.yaml" in str(printer.call_args_list[0])


class TestEnvOverridesAndTheServerLine:
    """DEPICTIO_CLI_TOKEN and DEPICTIO_CLI_API_BASE_URL: where they apply, and that the
    Server line says when the URL came from the environment."""

    @pytest.fixture(autouse=True)
    def isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        monkeypatch.delenv("DEPICTIO_CLI_CONFIG_PATH", raising=False)
        monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://remote.example.org")
        monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "remote-token")

    @pytest.fixture
    def named(self, tmp_path):
        path = tmp_path / "named.yaml"
        path.write_text(yaml.safe_dump(_valid_config("http://named.test")))
        return str(path)

    @pytest.fixture
    def local(self, tmp_path):
        path = tmp_path / "local" / "cli" / "admin_config.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))
        return path

    def test_the_server_line_names_the_env_var(self, named):
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            config = load_depictio_config(named)

        assert config.api_base_url == "https://remote.example.org"
        line = str(printer.call_args)
        assert "Server: https://remote.example.org (from DEPICTIO_CLI_API_BASE_URL," in line

    def test_the_local_server_ignores_them(self, local):
        from depictio.cli.cli.utils.server_target import resolve_server

        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            config = load_depictio_config(resolve_server("local"))

        assert config.api_base_url == "http://127.0.0.1:8058"
        assert config.user.token.access_token == "secret-access-token"
        assert "DEPICTIO_CLI_API_BASE_URL" not in str(printer.call_args)

    def test_they_can_be_set_aside(self, named):
        from depictio.cli.cli.utils.common import env_overrides_ignored

        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement"):
            with env_overrides_ignored():
                config = load_depictio_config(named)
            after = load_depictio_config(named)

        assert config.api_base_url == "http://named.test"
        assert after.api_base_url == "https://remote.example.org"

    def test_a_label_is_always_announced(self, named):
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            load_depictio_config(named, label="Source server")
            load_depictio_config(named, label="Target server")
            load_depictio_config(named)

        lines = [str(call.args[0]) for call in printer.call_args_list]
        assert [line.split(":")[0] for line in lines] == ["Source server", "Target server"]

    def test_the_log_names_no_token(self, named):
        with (
            patch("depictio.cli.cli.utils.common.rich_print_checked_statement"),
            patch("depictio.cli.cli.utils.common.logger") as log,
        ):
            load_depictio_config(named)

        logged = str(log.mock_calls)
        assert "remote-token" not in logged
        assert "admin@example.com" in logged


class TestLoopbackProxy:
    """A proxy in the environment cannot reach this machine's loopback."""

    @pytest.fixture
    def config(self, tmp_path, monkeypatch):
        for var in ("DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN", "no_proxy", "NO_PROXY"):
            monkeypatch.delenv(var, raising=False)
        path = tmp_path / "CLI.yaml"
        path.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))
        return str(path)

    def test_a_loopback_server_is_kept_off_the_proxy(self, config, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.org:3128")
        monkeypatch.setenv("no_proxy", ".example.org")

        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement"):
            load_depictio_config(config)
            load_depictio_config(config)

        assert os.environ["no_proxy"] == ".example.org,127.0.0.1,localhost"
        assert os.environ["NO_PROXY"] == os.environ["no_proxy"]

    def test_without_a_proxy_nothing_changes(self, config):
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement"):
            load_depictio_config(config)

        assert "no_proxy" not in os.environ


class TestDescribeApiTarget:
    """describe_api_target is called while reporting another error: it prints nothing."""

    @pytest.fixture(autouse=True)
    def isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    def test_a_missing_file_is_missing_not_unreadable(self, monkeypatch):
        # A remote server variable keeps the default file, missing or not.
        monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "https://remote.example.org")
        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            described = describe_api_target("~/.depictio/CLI.yaml")

        assert described == "a missing configuration at ~/.depictio/CLI.yaml"
        printer.assert_not_called()

    def test_a_broken_file_is_unreadable(self, tmp_path):
        config = tmp_path / "home" / "broken.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("user: [unclosed\n")

        with patch("depictio.cli.cli.utils.common.rich_print_checked_statement") as printer:
            described = describe_api_target(str(config))

        assert described == "an unreadable configuration at ~/broken.yaml"
        printer.assert_not_called()

    def test_a_stopped_local_server_says_how_to_start_it(self, tmp_path):
        from depictio.cli.cli.utils.server_target import resolve_server

        local = tmp_path / "local" / "cli" / "admin_config.yaml"
        local.parent.mkdir(parents=True)
        local.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))

        described = describe_api_target(resolve_server("local"))

        assert described.startswith("http://127.0.0.1:8058, read from ")
        assert "(the local server is not running: start it with `depictio local up`)" in described

    def test_the_local_server_by_default_gets_the_hint_too(self, tmp_path):
        local = tmp_path / "local" / "cli" / "admin_config.yaml"
        local.parent.mkdir(parents=True)
        local.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))

        described = describe_api_target("~/.depictio/CLI.yaml")

        assert described.startswith(f"http://127.0.0.1:8058, read from {local}")
        assert "start it with `depictio local up`" in described

    def test_another_server_gets_no_local_hint(self, tmp_path):
        config = tmp_path / "CLI.yaml"
        config.write_text(yaml.safe_dump(_valid_config("http://127.0.0.1:8058")))

        assert "depictio local up" not in describe_api_target(str(config))

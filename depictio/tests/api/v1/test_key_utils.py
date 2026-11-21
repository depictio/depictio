import os
import shutil
import stat
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

# Import the module assuming it's named crypto_utils.py
from depictio.api.v1.key_utils import (
    KeyGenerationError,
    _ensure_directory_exists,
    _generate_rsa_private_key,
    _resolve_key_paths,
    _save_private_key,
    _save_public_key,
    check_and_generate_keys,
    generate_keys,
    import_keys,
    load_private_key,
    load_public_key,
)


class TestCryptoUtils:
    """Test suite for crypto utility functions."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for the test."""
        temp_path = tempfile.mkdtemp()
        yield Path(temp_path)
        shutil.rmtree(temp_path)

    def test_ensure_directory_exists_with_string(self, temp_dir):
        """Test _ensure_directory_exists with string paths."""
        test_path = os.path.join(temp_dir, "test_dir", "file.txt")
        _ensure_directory_exists(test_path)
        assert os.path.isdir(os.path.dirname(test_path))

    def test_ensure_directory_exists_with_path(self, temp_dir):
        """Test _ensure_directory_exists with Path objects."""
        test_path = Path(temp_dir) / "test_dir" / "file.txt"
        _ensure_directory_exists(test_path)
        assert test_path.parent.is_dir()

    def test_resolve_key_paths_with_keys_dir(self, temp_dir):
        """Test _resolve_key_paths with keys_dir."""
        priv_path, pub_path = _resolve_key_paths(
            private_key_path=None, public_key_path=None, keys_dir=temp_dir
        )
        assert priv_path == str(temp_dir / "private_key.pem")
        assert pub_path == str(temp_dir / "public_key.pem")
        assert os.path.isdir(temp_dir)

    def test_resolve_key_paths_with_custom_paths(self, temp_dir):
        """Test _resolve_key_paths with custom paths."""
        priv_path = str(temp_dir / "custom_private.pem")
        pub_path = str(temp_dir / "custom_public.pem")
        resolved_priv, resolved_pub = _resolve_key_paths(
            private_key_path=priv_path, public_key_path=pub_path, keys_dir=None
        )
        assert resolved_priv == priv_path
        assert resolved_pub == pub_path

    def test_resolve_key_paths_with_keys_dir_string(self, temp_dir):
        """Test _resolve_key_paths with keys_dir as string."""
        priv_path, pub_path = _resolve_key_paths(
            private_key_path=None, public_key_path=None, keys_dir=str(temp_dir)
        )
        assert priv_path == str(Path(temp_dir) / "private_key.pem")
        assert pub_path == str(Path(temp_dir) / "public_key.pem")

    def test_resolve_key_paths_missing_paths(self):
        """Test _resolve_key_paths raises error with missing paths."""
        with pytest.raises(ValueError, match="Both key paths must be specified"):
            _resolve_key_paths(None, None, None)

    def test_generate_rsa_private_key(self):
        """Test _generate_rsa_private_key."""
        key = _generate_rsa_private_key(key_size=2048)
        assert isinstance(key, RSAPrivateKey)
        assert key.key_size == 2048

    def test_save_private_key(self, temp_dir):
        """Test _save_private_key."""
        key = _generate_rsa_private_key()
        path = temp_dir / "private_key.pem"
        _save_private_key(key, str(path))
        assert path.exists()
        # Check that the key can be loaded back
        with open(path, "rb") as f:
            # Use the serialization module instead of calling the method on the backend
            loaded_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
            assert isinstance(loaded_key, RSAPrivateKey)

    def test_save_public_key(self, temp_dir):
        """Test _save_public_key."""
        private_key = _generate_rsa_private_key()
        public_key = private_key.public_key()
        path = temp_dir / "public_key.pem"
        _save_public_key(public_key, str(path))
        assert path.exists()
        # Check that the key can be loaded back
        with open(path, "rb") as f:
            # Use the serialization module instead of calling the method on the backend
            loaded_key = serialization.load_pem_public_key(
                data=f.read(),  # type: ignore[call-arg]
                backend=default_backend(),
            )
            assert isinstance(loaded_key, RSAPublicKey)

    def test_generate_keys_rs256(self, temp_dir):
        """Test generate_keys with RS256 algorithm."""
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")
        result_priv, result_pub = generate_keys(
            private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256"
        )
        assert result_priv == priv_path
        assert result_pub == pub_path
        assert os.path.exists(priv_path)
        assert os.path.exists(pub_path)

        # Load keys to verify
        private_key = load_private_key(priv_path)
        public_key = load_public_key(pub_path)
        assert isinstance(private_key, RSAPrivateKey)
        assert isinstance(public_key, RSAPublicKey)
        assert private_key.key_size == 2048

    def test_generate_keys_rs512(self, temp_dir):
        """Test generate_keys with RS512 algorithm."""
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")
        generate_keys(private_key_path=priv_path, public_key_path=pub_path, algorithm="RS512")

        # Load key to verify key size
        private_key = load_private_key(priv_path)
        assert private_key.key_size == 4096

    def test_generate_keys_unsupported_algorithm(self, temp_dir):
        """Test generate_keys with unsupported algorithm."""
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            generate_keys(
                private_key_path=str(temp_dir / "private.pem"),
                public_key_path=str(temp_dir / "public.pem"),
                algorithm="UNSUPPORTED",  # type: ignore[arg-type]
            )

    def test_generate_keys_unimplemented_algorithm(self, temp_dir):
        """Test generate_keys with unimplemented algorithm."""
        with pytest.raises(NotImplementedError, match="ES256 algorithm is not implemented yet"):
            generate_keys(
                private_key_path=str(temp_dir / "private.pem"),
                public_key_path=str(temp_dir / "public.pem"),
                algorithm="ES256",
            )

    def test_generate_keys_with_exception(self, temp_dir):
        """Test generate_keys exception handling."""
        with mock.patch(
            "depictio.api.v1.key_utils._generate_rsa_private_key",
            side_effect=Exception("Test error"),
        ):
            with pytest.raises(KeyGenerationError, match="Failed to generate keys"):
                generate_keys(
                    private_key_path=str(temp_dir / "private.pem"),
                    public_key_path=str(temp_dir / "public.pem"),
                    algorithm="RS256",
                )

    def test_check_and_generate_keys_existing(self, temp_dir):
        """Test check_and_generate_keys with existing keys."""
        # First generate keys
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")
        generate_keys(private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256")

        # Now check if they exist
        with mock.patch("depictio.api.v1.key_utils.generate_keys") as mock_generate:
            result_priv, result_pub = check_and_generate_keys(
                private_key_path=priv_path, public_key_path=pub_path
            )
            assert result_priv == priv_path
            assert result_pub == pub_path
            mock_generate.assert_not_called()

    def test_check_and_generate_keys_missing(self, temp_dir):
        """Test check_and_generate_keys with missing keys."""
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")

        with mock.patch("depictio.api.v1.key_utils.generate_keys") as mock_generate:
            mock_generate.return_value = (priv_path, pub_path)
            check_and_generate_keys(
                private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256"
            )
            mock_generate.assert_called_once()

    def test_load_private_key_success(self, temp_dir):
        """Test successful loading of private key."""
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")
        generate_keys(private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256")

        key = load_private_key(priv_path)
        assert isinstance(key, RSAPrivateKey)

    def test_load_private_key_not_found(self, temp_dir):
        """Test load_private_key with non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_private_key(str(temp_dir / "nonexistent.pem"))

    def test_load_public_key_success(self, temp_dir):
        """Test successful loading of public key."""
        priv_path = str(temp_dir / "private.pem")
        pub_path = str(temp_dir / "public.pem")
        generate_keys(private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256")

        key = load_public_key(pub_path)
        assert isinstance(key, RSAPublicKey)

    def test_load_public_key_not_found(self, temp_dir):
        """Test load_public_key with non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_public_key(str(temp_dir / "nonexistent.pem"))

    def test_import_keys(self, temp_dir):
        """Test import_keys function."""
        # First generate a pair
        orig_priv_path = str(temp_dir / "original_private.pem")
        orig_pub_path = str(temp_dir / "original_public.pem")
        generate_keys(
            private_key_path=orig_priv_path,
            public_key_path=orig_pub_path,
            algorithm="RS256",
        )

        # Read key contents
        with open(orig_priv_path) as f:
            priv_content = f.read()
        with open(orig_pub_path) as f:
            pub_content = f.read()

        # Import to new location
        new_priv_path = str(temp_dir / "new_private.pem")
        new_pub_path = str(temp_dir / "new_public.pem")
        result_priv, result_pub = import_keys(
            private_key_content=priv_content,
            public_key_content=pub_content,
            private_key_path=new_priv_path,
            public_key_path=new_pub_path,
        )

        assert result_priv == new_priv_path
        assert result_pub == new_pub_path
        assert os.path.exists(new_priv_path)
        assert os.path.exists(new_pub_path)

        # Verify the keys can be loaded
        priv_key = load_private_key(new_priv_path)
        pub_key = load_public_key(new_pub_path)
        assert isinstance(priv_key, RSAPrivateKey)
        assert isinstance(pub_key, RSAPublicKey)


class TestPrivateKeyFilePermissions:
    """Private key files must be created owner-only (0600), never world-readable."""

    def test_save_private_key_creates_owner_only_file(self, tmp_path):
        """_save_private_key must create the file with mode 0600."""
        key = _generate_rsa_private_key()
        path = tmp_path / "private_key.pem"
        _save_private_key(key, str(path))
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    def test_generate_keys_private_key_is_owner_only(self, tmp_path):
        """generate_keys must persist the private key with mode 0600."""
        priv_path = str(tmp_path / "private.pem")
        pub_path = str(tmp_path / "public.pem")
        generate_keys(private_key_path=priv_path, public_key_path=pub_path, algorithm="RS256")

        assert stat.S_IMODE(os.stat(priv_path).st_mode) == 0o600
        # The public key is not secret and must remain readable by the owner.
        assert os.stat(pub_path).st_mode & stat.S_IRUSR

    def test_import_keys_private_key_is_owner_only(self, tmp_path):
        """import_keys must write the private key with mode 0600."""
        orig_priv_path = str(tmp_path / "original_private.pem")
        orig_pub_path = str(tmp_path / "original_public.pem")
        generate_keys(
            private_key_path=orig_priv_path, public_key_path=orig_pub_path, algorithm="RS256"
        )
        with open(orig_priv_path) as f:
            priv_content = f.read()
        with open(orig_pub_path) as f:
            pub_content = f.read()

        new_priv_path = str(tmp_path / "new_private.pem")
        new_pub_path = str(tmp_path / "new_public.pem")
        import_keys(
            private_key_content=priv_content,
            public_key_content=pub_content,
            private_key_path=new_priv_path,
            public_key_path=new_pub_path,
        )

        assert stat.S_IMODE(os.stat(new_priv_path).st_mode) == 0o600


class TestInternalApiKeyFilePermissions:
    """The API internal key file must be created owner-only (0600)."""

    def test_api_internal_key_file_is_owner_only(self, tmp_path):
        from depictio.api.v1.key_utils_base import _load_or_generate_api_internal_key

        # _generate_api_internal_key caches the key in the environment; keep
        # the change local so other tests see the original state.
        saved = os.environ.pop("DEPICTIO_INTERNAL_API_KEY", None)
        try:
            key = _load_or_generate_api_internal_key(keys_dir=tmp_path)
        finally:
            os.environ.pop("DEPICTIO_INTERNAL_API_KEY", None)
            if saved is not None:
                os.environ["DEPICTIO_INTERNAL_API_KEY"] = saved

        key_path = tmp_path / "api_internal_key.pem"
        assert key_path.exists()
        assert key  # the key itself is still returned
        assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600

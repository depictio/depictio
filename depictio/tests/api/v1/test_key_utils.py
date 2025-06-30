import os
import shutil
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

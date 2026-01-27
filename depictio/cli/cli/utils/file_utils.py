"""File utility functions for CLI operations."""

import hashlib
from pathlib import Path


def compute_file_hash(file_path: str, algorithm: str = "sha256", truncate: int = 12) -> str:
    """Compute content hash of file.

    Args:
        file_path: Path to file
        algorithm: Hash algorithm (default: sha256)
        truncate: Characters to keep (default: 12)

    Returns:
        Hex digest (truncated)

    Raises:
        FileNotFoundError: If file does not exist
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    hash_obj = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hash_obj.update(chunk)

    return hash_obj.hexdigest()[:truncate]

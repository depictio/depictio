import functools
from typing import List, Optional, Type

import bcrypt
import pytest
from beanie import Document, init_beanie
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from depictio.api.main import app


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def generate_hashed_password():
    """Fixture to generate a hashed password."""

    def _generate_hashed_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    return _generate_hashed_password


def beanie_setup(models: Optional[List[Type[Document]]] = None):
    """
    Decorator to initialize Beanie and AsyncMongoMockClient before running a test.
    This decorator allows specifying which models to initialize.

    Args:
        models: List of Beanie document models to initialize.
               If None, defaults to [TokenBeanie, UserBeanie].

    Example usage:
        @beanie_setup()  # Use default models
        async def test_function():
            ...

        @beanie_setup([CustomModel1, CustomModel2])  # Use custom models
        async def test_specific_models():
            ...
    """

    def decorator(func):
        @functools.wraps(func)  # Preserve function metadata for pytest
        async def wrapper(*args, **kwargs):
            # Initialize Beanie with the specified models
            client = AsyncMongoMockClient()
            await init_beanie(database=client.test_db, document_models=models)
            # Run the actual test function
            return await func(*args, **kwargs)

        # Make sure pytest recognizes this as an async test
        wrapper = pytest.mark.asyncio(wrapper)
        return wrapper

    return decorator

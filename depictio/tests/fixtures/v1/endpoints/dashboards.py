import pytest

@pytest.fixture(scope="session", autouse=True)
def dashboards() -> list:
    return ["dashboard_1"]
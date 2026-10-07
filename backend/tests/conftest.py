import os
from pathlib import Path

import pytest

# API tests need PostgreSQL. Point TEST_DATABASE_URL at an EMPTY test database - it is wiped.
# It always overrides DATABASE_URL (which may point at the real database, e.g. inside the backend
# container), and its name must end in "_test" so a real database can never be dropped by mistake.
_test_url = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://bom:bom@localhost:5432/bom_test")
if not _test_url.rsplit("?", 1)[0].rstrip("/").endswith("_test"):
    raise pytest.UsageError(f"TEST_DATABASE_URL must name a database ending in '_test' (got {_test_url!r}).")
os.environ["DATABASE_URL"] = _test_url

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_bytes() -> bytes:
    return (FIXTURES / "sample_input.xlsx").read_bytes()

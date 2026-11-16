import os
from collections.abc import Iterator

import pytest

from portfolio_api.store import InMemoryStore, Store

_TABLES = (
    "audit_event, ledger_reversal, tax_lot, holding, ledger_transaction, import_batch, "
    "portfolio, security, app_user"
)


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[Store]:
    """Every test using this fixture runs against both stores (Postgres when configured)."""
    if request.param == "memory":
        yield InMemoryStore()
        return
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL not set")
    pytest.importorskip("psycopg")
    from portfolio_api.store_postgres import PostgresStore, connect

    with connect(dsn) as conn:
        conn.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
        yield PostgresStore(conn)

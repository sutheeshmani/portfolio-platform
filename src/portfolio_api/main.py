"""Entry point: ``uvicorn portfolio_api.main:build --factory``.

Configuration comes from the environment only; nothing secret lives in code.

* ``DATABASE_URL``  e.g. ``postgresql://user:pass@localhost:5432/portfolio``
* ``API_TOKEN``     at least 32 characters; generate one with
  ``python -c "import secrets; print(secrets.token_urlsafe(32))"``
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from fastapi import FastAPI

from .app import StoreDependency, create_app
from .store import Store
from .store_postgres import PostgresStore, connect


def postgres_dependency(dsn: str) -> StoreDependency:
    def get_store() -> Iterator[Store]:
        with connect(dsn) as conn:  # one connection per request, closed afterwards
            yield PostgresStore(conn)

    return get_store


def build() -> FastAPI:
    try:
        dsn = os.environ["DATABASE_URL"]
        token = os.environ["API_TOKEN"]
    except KeyError as exc:
        raise RuntimeError(f"missing environment variable: {exc.args[0]}") from exc
    return create_app(postgres_dependency(dsn), token)

"""Persistence interface for the ledger, plus an in-memory implementation.

The store only saves and loads. Every accounting rule lives in the service and
the ``portfolio_core`` engine, so both stores behave identically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from portfolio_core.models import CostMethod, Transaction, fingerprint


class NotFound(LookupError):
    pass


class Conflict(Exception):
    pass


@dataclass(frozen=True)
class PortfolioRecord:
    id: str
    name: str
    base_currency: str
    cost_method: CostMethod
    objective: str | None
    created_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True)
class StoredTransaction:
    tx: Transaction
    fingerprint: str
    seq: int
    created_at: datetime
    reversed_at: datetime | None = None
    reversed_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.reversed_at is None


@dataclass(frozen=True)
class ImportBatch:
    source: str
    file_name: str | None
    file_sha256: str
    rows_valid: int
    rows_duplicate: int
    rows_rejected: int


@dataclass(frozen=True)
class AuditRecord:
    occurred_at: datetime
    action: str
    entity_type: str
    entity_id: str | None
    detail: dict[str, Any]


class Store(Protocol):
    def transaction(self) -> AbstractContextManager[None]:
        """All writes inside the block commit together or not at all."""

    def create_portfolio(
        self, name: str, base_currency: str, cost_method: CostMethod, objective: str | None
    ) -> PortfolioRecord: ...

    def list_portfolios(self, *, include_archived: bool = False) -> list[PortfolioRecord]: ...

    def get_portfolio(self, portfolio_id: str, *, for_update: bool = False) -> PortfolioRecord: ...

    def archive_portfolio(self, portfolio_id: str) -> PortfolioRecord: ...

    def exchange_currency(self, exchange: str) -> str | None: ...

    def transactions(self, portfolio_id: str) -> list[StoredTransaction]:
        """Every entry, reversed ones included, ordered by trade date then insertion."""

    def append(self, txs: Sequence[Transaction], batch: ImportBatch | None = None) -> None: ...

    def reverse(self, transaction_id: str, reason: str) -> None: ...

    def add_audit(
        self, action: str, entity_type: str, entity_id: str | None, detail: dict[str, Any]
    ) -> None: ...

    def audit(self, portfolio_id: str) -> list[AuditRecord]: ...


class InMemoryStore:
    """Reference implementation used by tests and local experiments."""

    _EXCHANGES = {"ASX": "AUD", "NASDAQ": "USD", "NYSE": "USD"}

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._portfolios: dict[str, PortfolioRecord] = {}
        self._txs: list[StoredTransaction] = []
        self._audit: list[AuditRecord] = []
        self._seq = 0
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._depth:
            yield
            return
        snapshot = (dict(self._portfolios), list(self._txs), list(self._audit), self._seq)
        self._depth += 1
        try:
            yield
        except BaseException:
            self._portfolios, self._txs, self._audit, self._seq = snapshot
            raise
        finally:
            self._depth -= 1

    def create_portfolio(
        self, name: str, base_currency: str, cost_method: CostMethod, objective: str | None
    ) -> PortfolioRecord:
        if any(p.name == name for p in self._portfolios.values()):
            raise Conflict(f"a portfolio named {name!r} already exists")
        record = PortfolioRecord(
            str(uuid4()), name, base_currency, cost_method, objective, self._clock()
        )
        self._portfolios[record.id] = record
        return record

    def list_portfolios(self, *, include_archived: bool = False) -> list[PortfolioRecord]:
        rows = sorted(self._portfolios.values(), key=lambda p: p.created_at)
        return [p for p in rows if include_archived or p.archived_at is None]

    def get_portfolio(self, portfolio_id: str, *, for_update: bool = False) -> PortfolioRecord:
        try:
            return self._portfolios[portfolio_id]
        except KeyError:
            raise NotFound(f"portfolio {portfolio_id} not found") from None

    def archive_portfolio(self, portfolio_id: str) -> PortfolioRecord:
        record = replace(self.get_portfolio(portfolio_id), archived_at=self._clock())
        self._portfolios[portfolio_id] = record
        return record

    def exchange_currency(self, exchange: str) -> str | None:
        return self._EXCHANGES.get(exchange)

    def transactions(self, portfolio_id: str) -> list[StoredTransaction]:
        rows = [s for s in self._txs if s.tx.portfolio_id == portfolio_id]
        return sorted(rows, key=lambda s: (s.tx.trade_date, s.seq))

    def append(self, txs: Sequence[Transaction], batch: ImportBatch | None = None) -> None:
        for tx in txs:
            self._seq += 1
            self._txs.append(StoredTransaction(tx, fingerprint(tx), self._seq, self._clock()))

    def reverse(self, transaction_id: str, reason: str) -> None:
        for i, stored in enumerate(self._txs):
            if stored.tx.id == transaction_id:
                self._txs[i] = replace(stored, reversed_at=self._clock(), reversed_reason=reason)
                return
        raise NotFound(f"transaction {transaction_id} not found")

    def add_audit(
        self, action: str, entity_type: str, entity_id: str | None, detail: dict[str, Any]
    ) -> None:
        self._audit.append(AuditRecord(self._clock(), action, entity_type, entity_id, detail))

    def audit(self, portfolio_id: str) -> list[AuditRecord]:
        return [a for a in self._audit if a.detail.get("portfolio_id") == portfolio_id]

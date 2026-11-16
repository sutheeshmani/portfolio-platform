"""Application service: the only place that writes to the ledger.

Every write happens inside one store transaction that first locks the portfolio,
re-checks the whole ledger with the calculation engine, then appends and audits.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import uuid4

from portfolio_core.engine import PortfolioState, replay
from portfolio_core.importers.csv_import import (
    ColumnMapping,
    ImportPreview,
    preview_import,
    suggest_mapping,
)
from portfolio_core.models import (
    CostMethod,
    DuplicateTransaction,
    LedgerError,
    Transaction,
    fingerprint,
)

from .store import AuditRecord, ImportBatch, PortfolioRecord, Store, StoredTransaction

MAX_SCALE = 8  # NUMERIC(24,8): anything finer would be silently rounded by the database
_DECIMAL_FIELDS = (
    "quantity", "unit_price", "amount", "brokerage_fee", "other_fees", "fx_rate_to_base",
)


@dataclass(frozen=True)
class ImportResult:
    mapping: ColumnMapping
    preview: ImportPreview
    committed: int


class PortfolioService:
    def __init__(self, store: Store) -> None:
        self.store = store

    # -- portfolios ------------------------------------------------------
    def create_portfolio(
        self,
        name: str,
        base_currency: str = "AUD",
        cost_method: CostMethod = CostMethod.FIFO,
        objective: str | None = None,
    ) -> PortfolioRecord:
        name = name.strip()
        if not name:
            raise LedgerError("portfolio name is required")
        with self.store.transaction():
            record = self.store.create_portfolio(name, base_currency, cost_method, objective)
            self.store.add_audit(
                "PORTFOLIO_CREATED", "portfolio", record.id,
                {"portfolio_id": record.id, "name": name, "base_currency": base_currency},
            )
        return record

    def list_portfolios(self, *, include_archived: bool = False) -> list[PortfolioRecord]:
        return self.store.list_portfolios(include_archived=include_archived)

    def get_portfolio(self, portfolio_id: str) -> PortfolioRecord:
        return self.store.get_portfolio(portfolio_id)

    def archive_portfolio(self, portfolio_id: str) -> PortfolioRecord:
        with self.store.transaction():
            self.store.get_portfolio(portfolio_id, for_update=True)
            record = self.store.archive_portfolio(portfolio_id)
            self.store.add_audit(
                "PORTFOLIO_ARCHIVED", "portfolio", portfolio_id, {"portfolio_id": portfolio_id}
            )
        return record

    # -- ledger ----------------------------------------------------------
    def record_transaction(
        self, tx: Transaction, *, allow_duplicate: bool = False, source: str = "manual"
    ) -> StoredTransaction:
        with self.store.transaction():
            portfolio = self._open_portfolio(tx.portfolio_id)
            self._check_new(tx)
            stored = self.store.transactions(portfolio.id)
            active = [s for s in stored if s.active]
            if not allow_duplicate and fingerprint(tx) in {s.fingerprint for s in active}:
                raise DuplicateTransaction("this matches a transaction already in the ledger")
            replay([*(s.tx for s in active), tx], portfolio.base_currency)
            self.store.append([tx])
            self.store.add_audit(
                "TRANSACTION_RECORDED", "transaction", tx.id,
                {"portfolio_id": portfolio.id, "source": source, "type": tx.type.value},
            )
            return next(s for s in self.store.transactions(portfolio.id) if s.tx.id == tx.id)

    def reverse_transaction(self, portfolio_id: str, transaction_id: str, reason: str) -> None:
        reason = reason.strip()
        if not reason:
            raise LedgerError("a reversal needs a reason")
        with self.store.transaction():
            portfolio = self.store.get_portfolio(portfolio_id, for_update=True)
            stored = self.store.transactions(portfolio.id)
            target = next((s for s in stored if s.tx.id == transaction_id), None)
            if target is None:
                raise LedgerError(f"transaction {transaction_id} is not in this portfolio")
            if not target.active:
                raise LedgerError("transaction is already reversed")
            remaining = [s.tx for s in stored if s.active and s.tx.id != transaction_id]
            replay(remaining, portfolio.base_currency)  # e.g. a buy whose shares were sold
            self.store.reverse(transaction_id, reason)
            self.store.add_audit(
                "TRANSACTION_REVERSED", "transaction", transaction_id,
                {"portfolio_id": portfolio.id, "reason": reason},
            )

    def list_transactions(self, portfolio_id: str) -> list[StoredTransaction]:
        self.store.get_portfolio(portfolio_id)
        return self.store.transactions(portfolio_id)

    def holdings(self, portfolio_id: str) -> tuple[PortfolioRecord, PortfolioState]:
        """Derived from the ledger on every call; nothing is cached yet."""
        portfolio = self.store.get_portfolio(portfolio_id)
        active = [s.tx for s in self.store.transactions(portfolio_id) if s.active]
        return portfolio, replay(active, portfolio.base_currency, portfolio.cost_method)

    def audit(self, portfolio_id: str) -> list[AuditRecord]:
        self.store.get_portfolio(portfolio_id)
        return self.store.audit(portfolio_id)

    # -- CSV import ------------------------------------------------------
    def import_csv(
        self,
        portfolio_id: str,
        text: str,
        *,
        mapping: ColumnMapping | None = None,
        commit: bool = False,
        file_name: str | None = None,
    ) -> ImportResult:
        """Preview, or with ``commit=True`` write every valid row in one transaction."""
        if mapping is None:
            headers = next(csv.reader(io.StringIO(text)), [])
            mapping = suggest_mapping(headers)
        with self.store.transaction():
            portfolio = self._open_portfolio(portfolio_id) if commit else (
                self.store.get_portfolio(portfolio_id)
            )
            active = [s for s in self.store.transactions(portfolio_id) if s.active]
            preview = preview_import(
                text, mapping, portfolio_id,
                base_currency=portfolio.base_currency,
                existing_fingerprints={s.fingerprint for s in active},
            )
            preview.valid = [replace(tx, id=str(uuid4())) for tx in preview.valid]
            if not commit or not preview.valid:
                return ImportResult(mapping, preview, 0)

            rows = sorted(preview.valid, key=lambda t: t.trade_date)
            for tx in rows:
                self._check_new(tx)
            replay([*(s.tx for s in active), *rows], portfolio.base_currency)
            batch = ImportBatch(
                source="csv",
                file_name=file_name,
                file_sha256=hashlib.sha256(text.encode()).hexdigest(),
                rows_valid=len(rows),
                rows_duplicate=len(preview.duplicates),
                rows_rejected=len(preview.errors),
            )
            self.store.append(rows, batch)
            self.store.add_audit(
                "IMPORT_COMMITTED", "portfolio", portfolio_id,
                {
                    "portfolio_id": portfolio_id,
                    "file_name": file_name,
                    "file_sha256": batch.file_sha256,
                    "rows_valid": batch.rows_valid,
                    "rows_duplicate": batch.rows_duplicate,
                    "rows_rejected": batch.rows_rejected,
                },
            )
            return ImportResult(mapping, preview, len(rows))

    # -- checks ----------------------------------------------------------
    def _open_portfolio(self, portfolio_id: str) -> PortfolioRecord:
        portfolio = self.store.get_portfolio(portfolio_id, for_update=True)
        if portfolio.archived_at is not None:
            raise LedgerError("portfolio is archived")
        return portfolio

    def _check_new(self, tx: Transaction) -> None:
        for name in _DECIMAL_FIELDS:
            value: Decimal | None = getattr(tx, name)
            if value is None:
                continue
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > MAX_SCALE:
                raise LedgerError(f"{name} has more than {MAX_SCALE} decimal places")
        if tx.security is not None:
            currency = self.store.exchange_currency(tx.security.exchange)
            if currency is None:
                raise LedgerError(f"unsupported exchange: {tx.security.exchange}")
            if currency != tx.currency:
                raise LedgerError(
                    f"{tx.security} trades in {currency}, but the transaction is in {tx.currency}"
                )

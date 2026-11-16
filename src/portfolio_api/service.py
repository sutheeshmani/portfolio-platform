"""Application service: the only place that writes to the ledger.

Every write happens inside one store transaction that first locks the portfolio,
re-checks the whole ledger with the calculation engine, then appends and audits.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from portfolio_core.engine import PortfolioState, replay
from portfolio_core.importers.csv_import import (
    ColumnMapping,
    ImportPreview,
    preview_import,
    suggest_mapping,
)
from portfolio_core.marketdata.base import MarketDataError, MarketDataProvider
from portfolio_core.models import (
    CostMethod,
    DuplicateTransaction,
    LedgerError,
    SecurityKey,
    Transaction,
    fingerprint,
)
from portfolio_core.valuation import FxQuote, PortfolioValuation, Quote, value_portfolio

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


@dataclass
class RefreshResult:
    quotes: dict[SecurityKey, Quote] = field(default_factory=dict)
    missing: dict[SecurityKey, str] = field(default_factory=dict)
    fx: dict[str, FxQuote] = field(default_factory=dict)
    fx_missing: dict[str, str] = field(default_factory=dict)


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

    # -- market data and valuation ----------------------------------------
    def refresh_prices(self, portfolio_id: str, provider: MarketDataProvider) -> RefreshResult:
        """Fetch prices for current holdings and FX for every foreign currency held.

        Network calls happen before the database transaction; results are then
        stored together. A provider failure for one item never blocks the rest.
        """
        portfolio, state = self.holdings(portfolio_id)
        result = RefreshResult()
        securities = sorted(state.positions)
        batch = getattr(provider, "get_quotes", None)
        if securities and callable(batch):
            result.quotes, result.missing = batch(securities)
        else:
            for sec in securities:
                try:
                    result.quotes[sec] = provider.get_quote(sec)
                except MarketDataError as exc:
                    result.missing[sec] = str(exc)

        currencies = {p.currency for p in state.positions.values()} | set(state.cash)
        for ccy in sorted(currencies - {portfolio.base_currency}):
            try:
                result.fx[ccy] = provider.get_fx(ccy, portfolio.base_currency)
            except MarketDataError as exc:
                result.fx_missing[ccy] = str(exc)

        with self.store.transaction():
            for quote in result.quotes.values():
                self.store.save_quote(quote)
            for fx in result.fx.values():
                self.store.save_fx(fx)
            self.store.add_audit(
                "PRICES_REFRESHED", "portfolio", portfolio_id,
                {
                    "portfolio_id": portfolio_id,
                    "updated": sorted(str(k) for k in result.quotes),
                    "missing": sorted(str(k) for k in result.missing),
                    "fx_updated": sorted(result.fx),
                    "fx_missing": sorted(result.fx_missing),
                },
            )
        return result

    def valuation(
        self, portfolio_id: str, as_of: datetime | None = None
    ) -> tuple[PortfolioRecord, PortfolioValuation]:
        """Values the portfolio from stored prices only; it never calls a provider."""
        portfolio, state = self.holdings(portfolio_id)
        quotes = self.store.latest_quotes(sorted(state.positions))
        currencies = {p.currency for p in state.positions.values()} | set(state.cash)
        fx_rates: dict[str, FxQuote] = {}
        for ccy in currencies - {portfolio.base_currency}:
            fx = self.store.latest_fx(ccy, portfolio.base_currency)
            if fx is not None:
                fx_rates[ccy] = fx
        return portfolio, value_portfolio(state, quotes, fx_rates, as_of or datetime.now(UTC))

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

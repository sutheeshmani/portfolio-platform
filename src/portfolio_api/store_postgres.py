"""PostgreSQL implementation of ``Store`` (psycopg 3).

The connection must be in autocommit mode: ``transaction()`` then issues a real
BEGIN/COMMIT, and nested calls become savepoints.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from portfolio_core.models import CostMethod, SecurityKey, Transaction, TxType, fingerprint
from portfolio_core.valuation import FxQuote, PriceType, Quote

from .store import (
    AuditRecord,
    Conflict,
    ImportBatch,
    NotFound,
    PortfolioRecord,
    StoredTransaction,
)

# Single-user application: one fixed owner row. Real identities arrive with the auth provider.
_OWNER_EMAIL = "owner@localhost"

_PORTFOLIO_COLUMNS = (
    "portfolio_id, portfolio_name, base_currency, cost_method, objective, created_at, archived_at"
)


def connect(dsn: str) -> psycopg.Connection[DictRow]:
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def _portfolio(row: DictRow) -> PortfolioRecord:
    return PortfolioRecord(
        id=str(row["portfolio_id"]),
        name=row["portfolio_name"],
        base_currency=row["base_currency"],
        cost_method=CostMethod(row["cost_method"]),
        objective=row["objective"],
        created_at=row["created_at"],
        archived_at=row["archived_at"],
    )


def _stored(row: DictRow) -> StoredTransaction:
    tx = Transaction(
        id=str(row["transaction_id"]),
        portfolio_id=str(row["portfolio_id"]),
        type=TxType(row["transaction_type"]),
        trade_date=row["trade_date"],
        currency=row["currency_code"],
        security=SecurityKey(row["symbol"], row["exchange_code"]) if row["symbol"] else None,
        quantity=row["quantity"],
        unit_price=row["unit_price"],
        amount=row["amount"],
        brokerage_fee=row["brokerage_fee"],
        other_fees=row["other_fees"],
        fx_rate_to_base=row["fx_rate_to_base"],
        settlement_date=row["settlement_date"],
        external_reference=row["external_reference"],
    )
    return StoredTransaction(
        tx=tx,
        fingerprint=row["fingerprint"],
        seq=row["ledger_seq"],
        created_at=row["created_at"],
        reversed_at=row["reversed_at"],
        reversed_reason=row["reason"],
    )


class PostgresStore:
    def __init__(self, conn: psycopg.Connection[DictRow]) -> None:
        if not conn.autocommit:
            raise ValueError("PostgresStore needs an autocommit connection")
        self._conn = conn
        self._user_id: Any = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._conn.transaction():
            yield

    def _owner(self) -> Any:
        if self._user_id is None:
            self._conn.execute(
                "INSERT INTO app_user (email) VALUES (%s) ON CONFLICT (email) DO NOTHING",
                (_OWNER_EMAIL,),
            )
            row = self._conn.execute(
                "SELECT user_id FROM app_user WHERE email = %s", (_OWNER_EMAIL,)
            ).fetchone()
            assert row is not None
            self._user_id = row["user_id"]
        return self._user_id

    # -- portfolios ------------------------------------------------------
    def create_portfolio(
        self, name: str, base_currency: str, cost_method: CostMethod, objective: str | None
    ) -> PortfolioRecord:
        try:
            with self._conn.transaction():
                row = self._conn.execute(
                    "INSERT INTO portfolio (user_id, portfolio_name, base_currency, cost_method,"
                    " objective) VALUES (%s, %s, %s, %s, %s) RETURNING " + _PORTFOLIO_COLUMNS,
                    (self._owner(), name, base_currency, cost_method.value, objective),
                ).fetchone()
        except UniqueViolation as exc:
            raise Conflict(f"a portfolio named {name!r} already exists") from exc
        assert row is not None
        return _portfolio(row)

    def list_portfolios(self, *, include_archived: bool = False) -> list[PortfolioRecord]:
        rows = self._conn.execute(
            "SELECT " + _PORTFOLIO_COLUMNS + " FROM portfolio WHERE user_id = %s"
            " AND (%s OR archived_at IS NULL) ORDER BY created_at, portfolio_name",
            (self._owner(), include_archived),
        ).fetchall()
        return [_portfolio(r) for r in rows]

    def get_portfolio(self, portfolio_id: str, *, for_update: bool = False) -> PortfolioRecord:
        query = (
            "SELECT " + _PORTFOLIO_COLUMNS + " FROM portfolio"
            " WHERE portfolio_id = %s::uuid AND user_id = %s"
        )
        if for_update:
            query += " FOR UPDATE"
        row = self._conn.execute(query, (portfolio_id, self._owner())).fetchone()
        if row is None:
            raise NotFound(f"portfolio {portfolio_id} not found")
        return _portfolio(row)

    def archive_portfolio(self, portfolio_id: str) -> PortfolioRecord:
        row = self._conn.execute(
            "UPDATE portfolio SET archived_at = COALESCE(archived_at, now()), updated_at = now()"
            " WHERE portfolio_id = %s::uuid AND user_id = %s RETURNING " + _PORTFOLIO_COLUMNS,
            (portfolio_id, self._owner()),
        ).fetchone()
        if row is None:
            raise NotFound(f"portfolio {portfolio_id} not found")
        return _portfolio(row)

    def exchange_currency(self, exchange: str) -> str | None:
        row = self._conn.execute(
            "SELECT currency_code FROM exchange WHERE exchange_code = %s", (exchange,)
        ).fetchone()
        return row["currency_code"] if row else None

    # -- ledger ----------------------------------------------------------
    def transactions(self, portfolio_id: str) -> list[StoredTransaction]:
        rows = self._conn.execute(
            "SELECT t.*, s.symbol, s.exchange_code, r.reason, r.reversed_at"
            " FROM ledger_transaction t"
            " LEFT JOIN security s ON s.security_id = t.security_id"
            " LEFT JOIN ledger_reversal r ON r.transaction_id = t.transaction_id"
            " WHERE t.portfolio_id = %s::uuid ORDER BY t.trade_date, t.ledger_seq",
            (portfolio_id,),
        ).fetchall()
        return [_stored(r) for r in rows]

    def _security_id(self, key: SecurityKey, currency: str) -> Any:
        # New securities start with the ticker as their name; market data fills it in later.
        row = self._conn.execute(
            "INSERT INTO security (symbol, company_name, exchange_code, currency_code, asset_type)"
            " VALUES (%s, %s, %s, %s, 'EQUITY')"
            " ON CONFLICT (symbol, exchange_code) DO UPDATE SET symbol = EXCLUDED.symbol"
            " RETURNING security_id",
            (key.symbol, key.symbol, key.exchange, currency),
        ).fetchone()
        assert row is not None
        return row["security_id"]

    def append(self, txs: Sequence[Transaction], batch: ImportBatch | None = None) -> None:
        if not txs:
            return
        with self._conn.transaction():
            batch_id = None
            if batch is not None:
                row = self._conn.execute(
                    "INSERT INTO import_batch (portfolio_id, source, file_name, file_sha256,"
                    " rows_valid, rows_duplicate, rows_rejected)"
                    " VALUES (%s::uuid, %s, %s, %s, %s, %s, %s) RETURNING import_batch_id",
                    (
                        txs[0].portfolio_id, batch.source, batch.file_name, batch.file_sha256,
                        batch.rows_valid, batch.rows_duplicate, batch.rows_rejected,
                    ),
                ).fetchone()
                assert row is not None
                batch_id = row["import_batch_id"]
            for tx in txs:
                security_id = (
                    self._security_id(tx.security, tx.currency) if tx.security else None
                )
                self._conn.execute(
                    "INSERT INTO ledger_transaction (transaction_id, portfolio_id, security_id,"
                    " transaction_type, trade_date, settlement_date, quantity, unit_price, amount,"
                    " currency_code, fx_rate_to_base, brokerage_fee, other_fees,"
                    " external_reference, fingerprint, import_batch_id)"
                    " VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " %s, %s, %s)",
                    (
                        tx.id, tx.portfolio_id, security_id, tx.type.value, tx.trade_date,
                        tx.settlement_date, tx.quantity, tx.unit_price, tx.amount, tx.currency,
                        tx.fx_rate_to_base, tx.brokerage_fee, tx.other_fees,
                        tx.external_reference, fingerprint(tx), batch_id,
                    ),
                )

    def reverse(self, transaction_id: str, reason: str) -> None:
        self._conn.execute(
            "INSERT INTO ledger_reversal (transaction_id, reason) VALUES (%s::uuid, %s)",
            (transaction_id, reason),
        )

    # -- audit -----------------------------------------------------------
    def add_audit(
        self, action: str, entity_type: str, entity_id: str | None, detail: dict[str, Any]
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_event (user_id, action, entity_type, entity_id, detail)"
            " VALUES (%s, %s, %s, %s::uuid, %s)",
            (self._owner(), action, entity_type, entity_id, Jsonb(detail)),
        )

    def audit(self, portfolio_id: str) -> list[AuditRecord]:
        rows = self._conn.execute(
            "SELECT occurred_at, action, entity_type, entity_id, detail FROM audit_event"
            " WHERE detail ->> 'portfolio_id' = %s ORDER BY occurred_at, audit_event_id",
            (portfolio_id,),
        ).fetchall()
        return [
            AuditRecord(
                r["occurred_at"], r["action"], r["entity_type"],
                str(r["entity_id"]) if r["entity_id"] else None, r["detail"],
            )
            for r in rows
        ]

    # -- market data -----------------------------------------------------
    def save_quote(self, quote: Quote) -> None:
        security_id = self._security_id(quote.security, quote.currency)
        self._conn.execute(
            "INSERT INTO market_price (security_id, price_timestamp, price_type, close_price,"
            " source) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (security_id, price_timestamp, price_type, source) DO NOTHING",
            (security_id, quote.as_of, quote.price_type.value, quote.price, quote.source),
        )

    def latest_quotes(self, securities: Sequence[SecurityKey]) -> dict[SecurityKey, Quote]:
        if not securities:
            return {}
        rows = self._conn.execute(
            "SELECT DISTINCT ON (s.security_id) s.symbol, s.exchange_code, s.currency_code,"
            " p.price_timestamp, p.price_type, p.close_price, p.source"
            " FROM market_price p JOIN security s ON s.security_id = p.security_id"
            " WHERE (s.symbol, s.exchange_code) IN (SELECT * FROM unnest(%s::text[], %s::text[]))"
            " ORDER BY s.security_id, p.price_timestamp DESC, p.fetched_at DESC",
            ([k.symbol for k in securities], [k.exchange for k in securities]),
        ).fetchall()
        out: dict[SecurityKey, Quote] = {}
        for r in rows:
            key = SecurityKey(r["symbol"], r["exchange_code"])
            out[key] = Quote(
                key, r["close_price"], r["currency_code"], r["price_timestamp"],
                PriceType(r["price_type"]), r["source"],
            )
        return out

    def save_fx(self, fx: FxQuote) -> None:
        self._conn.execute(
            "INSERT INTO fx_rate (from_currency, to_currency, rate, rate_timestamp, source)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (from_currency, to_currency, rate_timestamp, source) DO NOTHING",
            (fx.from_currency, fx.to_currency, fx.rate, fx.as_of, fx.source),
        )

    def latest_fx(self, from_currency: str, to_currency: str) -> FxQuote | None:
        row = self._conn.execute(
            "SELECT rate, rate_timestamp, source FROM fx_rate"
            " WHERE from_currency = %s AND to_currency = %s"
            " ORDER BY rate_timestamp DESC, fetched_at DESC LIMIT 1",
            (from_currency, to_currency),
        ).fetchone()
        if row is None:
            return None
        return FxQuote(
            from_currency, to_currency, row["rate"], row["rate_timestamp"], row["source"]
        )

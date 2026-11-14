"""Core ledger types.

All monetary values and quantities are ``decimal.Decimal``. Floats are rejected
at the boundary so binary floating point can never enter a calculation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal(0)

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,31}$")
_EXCHANGE_RE = re.compile(r"^[A-Z]{2,16}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class LedgerError(ValueError):
    """A transaction or ledger operation violates an accounting rule."""


class DuplicateTransaction(LedgerError):
    """The transaction matches one already in the ledger."""


class TxType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"


TRADE_TYPES = frozenset({TxType.BUY, TxType.SELL})


class CostMethod(StrEnum):
    """How disposals are matched to acquisition lots."""

    FIFO = "FIFO"
    AVERAGE = "AVERAGE"  # proportional across all open lots


@dataclass(frozen=True, order=True)
class SecurityKey:
    """Exchange-aware identifier. A ticker alone is never unique (BHP:ASX vs BHP:NYSE)."""

    symbol: str
    exchange: str

    def __post_init__(self) -> None:
        if not _SYMBOL_RE.match(self.symbol):
            raise LedgerError(f"invalid symbol: {self.symbol!r}")
        if not _EXCHANGE_RE.match(self.exchange):
            raise LedgerError(f"invalid exchange: {self.exchange!r}")

    def __str__(self) -> str:
        return f"{self.symbol}:{self.exchange}"


def _check_decimal(name: str, value: object, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise LedgerError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise LedgerError(f"{name} must be finite")
    if positive and value <= ZERO:
        raise LedgerError(f"{name} must be greater than zero")
    if not positive and value < ZERO:
        raise LedgerError(f"{name} must not be negative")


@dataclass(frozen=True)
class Transaction:
    """One immutable ledger entry.

    BUY / SELL use ``security``, ``quantity`` and ``unit_price``.
    DEPOSIT / WITHDRAWAL / DIVIDEND / FEE use ``amount`` (always positive; the
    type gives the direction). DIVIDEND may carry ``security``.

    ``fx_rate_to_base`` is base-currency units per 1 unit of ``currency`` on the
    trade date. It is preserved forever and never replaced by a current rate.
    """

    id: str
    portfolio_id: str
    type: TxType
    trade_date: datetime
    currency: str
    security: SecurityKey | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    brokerage_fee: Decimal = ZERO
    other_fees: Decimal = ZERO
    fx_rate_to_base: Decimal | None = None
    settlement_date: date | None = None
    external_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.portfolio_id:
            raise LedgerError("id and portfolio_id are required")
        if self.trade_date.tzinfo is None:
            raise LedgerError("trade_date must be timezone-aware")
        if not _CURRENCY_RE.match(self.currency):
            raise LedgerError(f"invalid currency: {self.currency!r}")
        _check_decimal("brokerage_fee", self.brokerage_fee)
        _check_decimal("other_fees", self.other_fees)
        if self.fx_rate_to_base is not None:
            _check_decimal("fx_rate_to_base", self.fx_rate_to_base, positive=True)

        if self.type in TRADE_TYPES:
            if self.security is None:
                raise LedgerError(f"{self.type} requires a security")
            _check_decimal("quantity", self.quantity, positive=True)
            _check_decimal("unit_price", self.unit_price, positive=True)
            if self.amount is not None:
                raise LedgerError(f"{self.type} must not set amount")
        else:
            _check_decimal("amount", self.amount, positive=True)
            if self.quantity is not None or self.unit_price is not None:
                raise LedgerError(f"{self.type} must not set quantity or unit_price")
            if self.security is not None and self.type is not TxType.DIVIDEND:
                raise LedgerError(f"{self.type} must not set a security")

    @property
    def fees(self) -> Decimal:
        return self.brokerage_fee + self.other_fees


def _norm(value: Decimal | None) -> str:
    return "" if value is None else format(value.normalize(), "f")


def fingerprint(tx: Transaction) -> str:
    """Stable hash used for duplicate detection and idempotent imports.

    If the broker supplied a reference it alone identifies the trade; otherwise
    the economic fields do.
    """
    if tx.external_reference:
        parts = [tx.portfolio_id, "ref", tx.external_reference.strip()]
    else:
        parts = [
            tx.portfolio_id,
            tx.type.value,
            str(tx.security) if tx.security else "",
            tx.trade_date.isoformat(),
            tx.currency,
            _norm(tx.quantity),
            _norm(tx.unit_price),
            _norm(tx.amount),
            _norm(tx.fees),
        ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()

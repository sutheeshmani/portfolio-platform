"""Broker CSV import: map columns, validate, detect duplicates, preview.

``preview_import`` never writes anything. The caller shows the preview, the user
confirms, and ``commit_import`` records the valid rows. Re-importing the same
file is a no-op because every row is matched against ledger fingerprints.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from ..ledger import Ledger
from ..models import ZERO, LedgerError, SecurityKey, Transaction, TxType, fingerprint

_TYPE_ALIASES = {
    "B": TxType.BUY,
    "BUY": TxType.BUY,
    "BOUGHT": TxType.BUY,
    "S": TxType.SELL,
    "SELL": TxType.SELL,
    "SOLD": TxType.SELL,
}

# Header names seen across broker exports, used only to *suggest* a mapping.
_HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "date": ("trade date", "date", "transaction date", "date (us)"),
    "type": ("side", "type", "transaction type", "buy/sell", "action"),
    "symbol": ("symbol", "code", "stock code", "ticker", "security"),
    "quantity": ("units", "quantity", "qty", "shares"),
    "price": ("effective price", "avg. price", "average price", "unit price", "price"),
    "fees": ("brokerage fee", "brokerage", "fees", "commission"),
    "currency": ("currency", "ccy"),
    "exchange": ("exchange", "market"),
    "reference": ("reference", "order id", "contract note", "confirmation number", "trade id"),
    "fx_rate": ("aud/usd rate", "fx rate", "exchange rate"),
}


@dataclass(frozen=True)
class ColumnMapping:
    """Which CSV column feeds which field. Optional columns may be ``None``."""

    date: str
    type: str
    symbol: str
    quantity: str
    price: str
    fees: str | None = None
    currency: str | None = None
    exchange: str | None = None
    reference: str | None = None
    fx_rate: str | None = None  # base units per 1 unit of trade currency
    date_format: str = "%d/%m/%Y"
    default_exchange: str = "ASX"
    default_currency: str = "AUD"
    timezone: str = "Australia/Sydney"


def suggest_mapping(headers: list[str], **defaults: str) -> ColumnMapping:
    """Guess a mapping from header names. The user must review it before importing."""
    lookup = {h.strip().lower(): h for h in headers}
    found: dict[str, str] = {}
    for field_name, hints in _HEADER_HINTS.items():
        for hint in hints:
            if hint in lookup:
                found[field_name] = lookup[hint]
                break
    missing = [f for f in ("date", "type", "symbol", "quantity", "price") if f not in found]
    if missing:
        raise LedgerError(f"could not find columns for: {', '.join(missing)}")
    return ColumnMapping(**found, **defaults)


@dataclass(frozen=True)
class RowIssue:
    line: int  # 1-based line in the file, header is line 1
    reason: str
    raw: dict[str, str]


@dataclass
class ImportPreview:
    valid: list[Transaction] = field(default_factory=list)
    duplicates: list[RowIssue] = field(default_factory=list)
    errors: list[RowIssue] = field(default_factory=list)


def _decimal(raw: str, name: str) -> Decimal:
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if not cleaned:
        raise LedgerError(f"{name} is empty")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise LedgerError(f"{name} is not a number: {raw!r}") from exc
    return abs(value)  # some brokers sign sells negative; the type column gives direction


def preview_import(
    text: str,
    mapping: ColumnMapping,
    portfolio_id: str,
    *,
    base_currency: str = "AUD",
    existing_fingerprints: set[str] | None = None,
    id_prefix: str = "imp",
) -> ImportPreview:
    preview = ImportPreview()
    seen = set(existing_fingerprints or ())
    tz = ZoneInfo(mapping.timezone)
    reader = csv.DictReader(io.StringIO(text))

    for line, row in enumerate(reader, start=2):
        raw = {k: (v or "") for k, v in row.items() if k is not None}
        if not any(v.strip() for v in raw.values()):
            continue
        try:
            tx_type = _TYPE_ALIASES.get(raw[mapping.type].strip().upper())
            if tx_type is None:
                raise LedgerError(f"unsupported transaction type: {raw[mapping.type]!r}")
            currency = (
                raw[mapping.currency].strip().upper() if mapping.currency else ""
            ) or mapping.default_currency
            exchange = (
                raw[mapping.exchange].strip().upper() if mapping.exchange else ""
            ) or mapping.default_exchange
            fx_rate = (
                _decimal(raw[mapping.fx_rate], "fx_rate")
                if mapping.fx_rate and raw[mapping.fx_rate].strip()
                else None
            )
            if currency != base_currency and fx_rate is None:
                raise LedgerError(f"{currency} trade has no FX rate to {base_currency}")
            reference = raw[mapping.reference].strip() if mapping.reference else ""
            trade_date = datetime.strptime(raw[mapping.date].strip(), mapping.date_format)
            tx = Transaction(
                id=f"{id_prefix}-{line}",
                portfolio_id=portfolio_id,
                type=tx_type,
                trade_date=trade_date.replace(tzinfo=tz),
                currency=currency,
                # SecurityKey's strict pattern also rejects spreadsheet formulas (=, +, @ ...).
                security=SecurityKey(raw[mapping.symbol].strip().upper(), exchange),
                quantity=_decimal(raw[mapping.quantity], "quantity"),
                unit_price=_decimal(raw[mapping.price], "price"),
                brokerage_fee=(
                    _decimal(raw[mapping.fees], "fees")
                    if mapping.fees and raw[mapping.fees].strip()
                    else ZERO
                ),
                fx_rate_to_base=fx_rate,
                external_reference=reference or None,
            )
        except KeyError as exc:
            preview.errors.append(RowIssue(line, f"column not found: {exc.args[0]}", raw))
            continue
        except (LedgerError, ValueError) as exc:
            preview.errors.append(RowIssue(line, str(exc), raw))
            continue

        fp = fingerprint(tx)
        if fp in seen:
            preview.duplicates.append(RowIssue(line, "duplicate of an existing transaction", raw))
            continue
        seen.add(fp)
        preview.valid.append(tx)
    return preview


def commit_import(ledger: Ledger, preview: ImportPreview, *, source: str = "csv") -> int:
    """Record previewed rows in date order. All-or-nothing: on failure the ledger is unchanged."""
    snapshot = (list(ledger._entries), list(ledger.audit))  # noqa: SLF001
    try:
        for tx in sorted(preview.valid, key=lambda t: t.trade_date):
            ledger.record(tx, actor="import", source=source)
    except LedgerError:
        ledger._entries, ledger.audit = snapshot  # noqa: SLF001
        raise
    return len(preview.valid)


def escape_csv_cell(value: str) -> str:
    """Neutralise spreadsheet formulas when exporting user-supplied text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

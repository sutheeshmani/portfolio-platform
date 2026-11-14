"""Portfolio valuation in the base currency.

Rules from the PRD:
* every price and FX rate carries its source, type and timestamp;
* a missing price is reported, never guessed, and the totals are marked incomplete;
* a stale price is used but flagged;
* current valuation FX is kept separate from the transaction-date FX in the cost base.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .engine import PortfolioState
from .models import ZERO, SecurityKey

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round for display only. Calculations keep full precision."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class PriceType(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    EOD = "EOD"


@dataclass(frozen=True)
class Quote:
    security: SecurityKey
    price: Decimal
    currency: str
    as_of: datetime
    price_type: PriceType
    source: str


@dataclass(frozen=True)
class FxQuote:
    from_currency: str
    to_currency: str
    rate: Decimal  # to_currency units per 1 from_currency
    as_of: datetime
    source: str


@dataclass(frozen=True)
class HoldingValuation:
    security: SecurityKey
    currency: str
    quantity: Decimal
    cost_local: Decimal
    cost_base: Decimal
    quote: Quote | None = None
    fx: FxQuote | None = None
    market_value_local: Decimal | None = None
    market_value_base: Decimal | None = None
    unrealised_local: Decimal | None = None
    unrealised_base: Decimal | None = None
    price_effect_base: Decimal | None = None  # price move at today's FX
    fx_effect_base: Decimal | None = None  # FX move on the original cost
    weight: Decimal | None = None
    stale: bool = False
    issue: str | None = None

    @property
    def priced(self) -> bool:
        return self.market_value_base is not None


@dataclass
class PortfolioValuation:
    base_currency: str
    as_of: datetime
    holdings: list[HoldingValuation] = field(default_factory=list)
    cash_local: dict[str, Decimal] = field(default_factory=dict)
    cash_base: dict[str, Decimal] = field(default_factory=dict)
    holdings_value_base: Decimal = ZERO
    cash_value_base: Decimal = ZERO
    unrealised_base: Decimal = ZERO
    realised_base: Decimal = ZERO
    currency_exposure_base: dict[str, Decimal] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when any holding or cash balance could not be valued."""
        return not any(i.startswith("MISSING") for i in self.issues)

    @property
    def total_value_base(self) -> Decimal:
        """Value of everything that could be priced. Check ``complete`` before trusting it."""
        return self.holdings_value_base + self.cash_value_base


def value_portfolio(
    state: PortfolioState,
    quotes: Mapping[SecurityKey, Quote],
    fx_rates: Mapping[str, FxQuote],
    as_of: datetime,
    *,
    max_quote_age: timedelta = timedelta(days=4),
    max_fx_age: timedelta = timedelta(days=4),
) -> PortfolioValuation:
    """Value ``state``. ``fx_rates`` maps a foreign currency code to its rate into base."""
    base = state.base_currency
    out = PortfolioValuation(
        base_currency=base, as_of=as_of, realised_base=state.realised_gain_base
    )

    def rate_for(currency: str) -> tuple[Decimal, FxQuote | None, str | None, bool]:
        if currency == base:
            return Decimal(1), None, None, False
        fx = fx_rates.get(currency)
        if fx is None or fx.from_currency != currency or fx.to_currency != base:
            return ZERO, None, f"MISSING_FX {currency}->{base}", False
        return fx.rate, fx, None, as_of - fx.as_of > max_fx_age

    rows: list[HoldingValuation] = []
    for key in sorted(state.positions):
        pos = state.positions[key]
        common = dict(
            security=key,
            currency=pos.currency,
            quantity=pos.quantity,
            cost_local=pos.cost_local,
            cost_base=pos.cost_base,
        )
        quote = quotes.get(key)
        if quote is None:
            issue = f"MISSING_PRICE {key}"
        elif quote.currency != pos.currency:
            issue = f"MISSING_PRICE {key} (quote in {quote.currency}, held in {pos.currency})"
        else:
            issue = None
        rate, fx, fx_issue, fx_stale = rate_for(pos.currency)
        issue = issue or fx_issue
        if issue or quote is None:
            out.issues.append(issue or f"MISSING_PRICE {key}")
            rows.append(HoldingValuation(**common, quote=quote, fx=fx, issue=issue))  # type: ignore[arg-type]
            continue

        mv_local = pos.quantity * quote.price
        mv_base = mv_local * rate
        stale = fx_stale or (as_of - quote.as_of > max_quote_age)
        if stale:
            out.issues.append(f"STALE {key} price as of {quote.as_of.isoformat()}")
        rows.append(
            HoldingValuation(
                **common,  # type: ignore[arg-type]
                quote=quote,
                fx=fx,
                market_value_local=mv_local,
                market_value_base=mv_base,
                unrealised_local=mv_local - pos.cost_local,
                unrealised_base=mv_base - pos.cost_base,
                price_effect_base=(mv_local - pos.cost_local) * rate,
                fx_effect_base=pos.cost_local * rate - pos.cost_base,
                stale=stale,
            )
        )
        out.holdings_value_base += mv_base
        out.unrealised_base += mv_base - pos.cost_base
        out.currency_exposure_base[pos.currency] = (
            out.currency_exposure_base.get(pos.currency, ZERO) + mv_base
        )

    for currency, balance in sorted(state.cash.items()):
        out.cash_local[currency] = balance
        rate, _, fx_issue, fx_stale = rate_for(currency)
        if fx_issue:
            out.issues.append(f"{fx_issue} (cash)")
            continue
        if fx_stale:
            out.issues.append(f"STALE FX {currency}->{base}")
        value = balance * rate
        out.cash_base[currency] = value
        out.cash_value_base += value
        out.currency_exposure_base[currency] = (
            out.currency_exposure_base.get(currency, ZERO) + value
        )

    total = out.total_value_base
    out.holdings = [
        _with_weight(r, r.market_value_base / total)
        if r.market_value_base is not None and total > ZERO
        else r
        for r in rows
    ]
    return out


def _with_weight(row: HoldingValuation, weight: Decimal) -> HoldingValuation:
    from dataclasses import replace

    return replace(row, weight=weight)

"""Deterministic replay of the transaction ledger into positions, lots, cash and realised P&L.

The ledger is the source of truth: holdings are always derived by calling
``replay`` and are never edited directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .models import ZERO, CostMethod, LedgerError, SecurityKey, Transaction, TxType


@dataclass
class Lot:
    """One acquisition parcel. Costs include buy-side fees."""

    lot_id: str  # id of the BUY transaction
    security: SecurityKey
    acquired: datetime
    quantity: Decimal
    cost_local: Decimal
    cost_base: Decimal


@dataclass(frozen=True)
class RealisedGain:
    sell_tx_id: str
    lot_id: str
    security: SecurityKey
    currency: str
    quantity: Decimal
    acquired: datetime
    disposed: datetime
    proceeds_local: Decimal  # net of sell-side fees
    cost_local: Decimal
    proceeds_base: Decimal
    cost_base: Decimal

    @property
    def gain_local(self) -> Decimal:
        return self.proceeds_local - self.cost_local

    @property
    def gain_base(self) -> Decimal:
        return self.proceeds_base - self.cost_base


@dataclass
class Position:
    security: SecurityKey
    currency: str
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), ZERO)

    @property
    def cost_local(self) -> Decimal:
        return sum((lot.cost_local for lot in self.lots), ZERO)

    @property
    def cost_base(self) -> Decimal:
        return sum((lot.cost_base for lot in self.lots), ZERO)

    @property
    def average_cost(self) -> Decimal | None:
        qty = self.quantity
        return self.cost_local / qty if qty else None


@dataclass(frozen=True)
class DividendIncome:
    tx_id: str
    security: SecurityKey | None
    currency: str
    paid: datetime
    amount_local: Decimal
    amount_base: Decimal


@dataclass
class PortfolioState:
    base_currency: str
    positions: dict[SecurityKey, Position] = field(default_factory=dict)
    cash: dict[str, Decimal] = field(default_factory=dict)
    realised: list[RealisedGain] = field(default_factory=list)
    dividends: list[DividendIncome] = field(default_factory=list)
    net_contributions_base: Decimal = ZERO  # deposits less withdrawals
    standalone_fees_base: Decimal = ZERO
    warnings: list[str] = field(default_factory=list)

    @property
    def realised_gain_base(self) -> Decimal:
        return sum((g.gain_base for g in self.realised), ZERO)

    @property
    def dividend_income_base(self) -> Decimal:
        return sum((d.amount_base for d in self.dividends), ZERO)


def replay(
    transactions: Iterable[Transaction],
    base_currency: str,
    method: CostMethod = CostMethod.FIFO,
) -> PortfolioState:
    """Apply transactions in trade-date order (input order breaks ties)."""
    state = PortfolioState(base_currency=base_currency)
    ordered = sorted(enumerate(transactions), key=lambda p: (p[1].trade_date, p[0]))
    seen: set[str] = set()
    for _, tx in ordered:
        if tx.id in seen:
            raise LedgerError(f"duplicate transaction id: {tx.id}")
        seen.add(tx.id)
        _apply(state, tx, method)
    state.positions = {k: p for k, p in state.positions.items() if p.lots}
    return state


def _fx(state: PortfolioState, tx: Transaction) -> Decimal:
    if tx.currency == state.base_currency:
        return Decimal(1)
    if tx.fx_rate_to_base is None:
        raise LedgerError(
            f"{tx.id}: {tx.currency} transaction needs fx_rate_to_base ({state.base_currency})"
        )
    return tx.fx_rate_to_base


def _move_cash(state: PortfolioState, tx: Transaction, delta: Decimal) -> None:
    balance = state.cash.get(tx.currency, ZERO) + delta
    state.cash[tx.currency] = balance
    if balance < ZERO:
        state.warnings.append(
            f"{tx.id}: {tx.currency} cash balance is negative ({balance}) "
            "- a deposit is probably missing from the ledger"
        )


def _apply(state: PortfolioState, tx: Transaction, method: CostMethod) -> None:
    fx = _fx(state, tx)
    if tx.type is TxType.BUY:
        _buy(state, tx, fx)
    elif tx.type is TxType.SELL:
        _sell(state, tx, fx, method)
    else:
        assert tx.amount is not None
        if tx.type is TxType.DEPOSIT:
            _move_cash(state, tx, tx.amount)
            state.net_contributions_base += tx.amount * fx
        elif tx.type is TxType.WITHDRAWAL:
            _move_cash(state, tx, -tx.amount)
            state.net_contributions_base -= tx.amount * fx
        elif tx.type is TxType.DIVIDEND:
            _move_cash(state, tx, tx.amount)
            state.dividends.append(
                DividendIncome(
                    tx.id, tx.security, tx.currency, tx.trade_date, tx.amount, tx.amount * fx
                )
            )
        elif tx.type is TxType.FEE:
            _move_cash(state, tx, -tx.amount)
            state.standalone_fees_base += tx.amount * fx


def _buy(state: PortfolioState, tx: Transaction, fx: Decimal) -> None:
    assert tx.security and tx.quantity is not None and tx.unit_price is not None
    cost_local = tx.quantity * tx.unit_price + tx.fees
    pos = state.positions.get(tx.security)
    if pos is None:
        pos = state.positions[tx.security] = Position(tx.security, tx.currency)
    elif pos.currency != tx.currency:
        raise LedgerError(f"{tx.id}: {tx.security} is held in {pos.currency}, not {tx.currency}")
    pos.lots.append(
        Lot(tx.id, tx.security, tx.trade_date, tx.quantity, cost_local, cost_local * fx)
    )
    _move_cash(state, tx, -cost_local)


def _sell(state: PortfolioState, tx: Transaction, fx: Decimal, method: CostMethod) -> None:
    assert tx.security and tx.quantity is not None and tx.unit_price is not None
    qty = tx.quantity
    pos = state.positions.get(tx.security)
    held = pos.quantity if pos else ZERO
    if pos is None or qty > held:
        raise LedgerError(f"{tx.id}: cannot sell {qty} {tx.security}, only {held} held")
    if pos.currency != tx.currency:
        raise LedgerError(f"{tx.id}: {tx.security} is held in {pos.currency}, not {tx.currency}")

    proceeds_local = qty * tx.unit_price - tx.fees

    takes: list[tuple[Lot, Decimal]] = []
    if method is CostMethod.FIFO:
        remaining = qty
        for lot in pos.lots:
            if not remaining:
                break
            take = min(lot.quantity, remaining)
            takes.append((lot, take))
            remaining -= take
    else:
        allocated = ZERO
        last = len(pos.lots) - 1
        for i, lot in enumerate(pos.lots):
            take = qty - allocated if i == last else lot.quantity * qty / held
            take = min(take, lot.quantity)
            allocated += take
            takes.append((lot, take))

    proceeds_left = proceeds_local
    for i, (lot, take) in enumerate(takes):
        whole = take == lot.quantity
        cost_local = lot.cost_local if whole else lot.cost_local * take / lot.quantity
        cost_base = lot.cost_base if whole else lot.cost_base * take / lot.quantity
        # The last slice takes the remainder so slices always sum to the total.
        share = proceeds_left if i == len(takes) - 1 else proceeds_local * take / qty
        proceeds_left -= share
        state.realised.append(
            RealisedGain(
                sell_tx_id=tx.id,
                lot_id=lot.lot_id,
                security=tx.security,
                currency=tx.currency,
                quantity=take,
                acquired=lot.acquired,
                disposed=tx.trade_date,
                proceeds_local=share,
                cost_local=cost_local,
                proceeds_base=share * fx,
                cost_base=cost_base,
            )
        )
        lot.quantity -= take
        lot.cost_local -= cost_local
        lot.cost_base -= cost_base

    pos.lots = [lot for lot in pos.lots if lot.quantity > ZERO]
    _move_cash(state, tx, proceeds_local)

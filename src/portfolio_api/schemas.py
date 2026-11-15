"""Request and response models. Money and quantities travel as JSON strings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from portfolio_core.engine import PortfolioState
from portfolio_core.importers.csv_import import ColumnMapping, RowIssue
from portfolio_core.models import CostMethod, SecurityKey, Transaction, TxType

from .store import AuditRecord, PortfolioRecord, StoredTransaction

_EIGHT_DP = Decimal("0.00000001")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimal values as strings, e.g. \"10.25\"")
    return value


Dec = Annotated[
    Decimal, BeforeValidator(_reject_float), Field(max_digits=24, decimal_places=8, ge=0)
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioIn(_In):
    name: str = Field(min_length=1, max_length=128)
    base_currency: Currency = "AUD"
    cost_method: CostMethod = CostMethod.FIFO
    objective: str | None = Field(default=None, max_length=2000)


class PortfolioOut(BaseModel):
    id: str
    name: str
    base_currency: str
    cost_method: CostMethod
    objective: str | None
    created_at: datetime
    archived_at: datetime | None

    @classmethod
    def of(cls, p: PortfolioRecord) -> PortfolioOut:
        return cls(
            id=p.id, name=p.name, base_currency=p.base_currency, cost_method=p.cost_method,
            objective=p.objective, created_at=p.created_at, archived_at=p.archived_at,
        )


class TransactionIn(_In):
    portfolio_id: UUID
    type: TxType
    trade_date: AwareDatetime
    currency: Currency
    symbol: str | None = Field(default=None, max_length=32)
    exchange: str | None = Field(default=None, max_length=16)
    quantity: Dec | None = None
    unit_price: Dec | None = None
    amount: Dec | None = None
    brokerage_fee: Dec = Decimal(0)
    other_fees: Dec = Decimal(0)
    fx_rate_to_base: Dec | None = None
    settlement_date: date | None = None
    external_reference: str | None = Field(default=None, max_length=128)
    allow_duplicate: bool = False

    def to_transaction(self, transaction_id: str) -> Transaction:
        """Raises ``LedgerError`` when the fields do not suit the transaction type."""
        security = None
        if self.symbol or self.exchange:
            security = SecurityKey((self.symbol or "").upper(), (self.exchange or "").upper())
        return Transaction(
            id=transaction_id,
            portfolio_id=str(self.portfolio_id),
            type=self.type,
            trade_date=self.trade_date,
            currency=self.currency,
            security=security,
            quantity=self.quantity,
            unit_price=self.unit_price,
            amount=self.amount,
            brokerage_fee=self.brokerage_fee,
            other_fees=self.other_fees,
            fx_rate_to_base=self.fx_rate_to_base,
            settlement_date=self.settlement_date,
            external_reference=self.external_reference,
        )


class TransactionOut(BaseModel):
    id: str
    portfolio_id: str
    type: TxType
    trade_date: datetime
    currency: str
    symbol: str | None
    exchange: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    brokerage_fee: Decimal
    other_fees: Decimal
    fx_rate_to_base: Decimal | None
    settlement_date: date | None
    external_reference: str | None
    reversed: bool = False
    reversed_reason: str | None = None

    @classmethod
    def of_tx(cls, tx: Transaction) -> TransactionOut:
        return cls(
            id=tx.id, portfolio_id=tx.portfolio_id, type=tx.type, trade_date=tx.trade_date,
            currency=tx.currency,
            symbol=tx.security.symbol if tx.security else None,
            exchange=tx.security.exchange if tx.security else None,
            quantity=tx.quantity, unit_price=tx.unit_price, amount=tx.amount,
            brokerage_fee=tx.brokerage_fee, other_fees=tx.other_fees,
            fx_rate_to_base=tx.fx_rate_to_base, settlement_date=tx.settlement_date,
            external_reference=tx.external_reference,
        )

    @classmethod
    def of(cls, stored: StoredTransaction) -> TransactionOut:
        out = cls.of_tx(stored.tx)
        out.reversed = not stored.active
        out.reversed_reason = stored.reversed_reason
        return out


class ReversalIn(_In):
    portfolio_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class LotOut(BaseModel):
    lot_id: str
    acquired: datetime
    quantity: Decimal
    cost_local: Decimal
    cost_base: Decimal


class PositionOut(BaseModel):
    symbol: str
    exchange: str
    currency: str
    quantity: Decimal
    average_cost: Decimal | None
    cost_local: Decimal
    cost_base: Decimal
    lots: list[LotOut]


class HoldingsOut(BaseModel):
    portfolio_id: str
    base_currency: str
    cost_method: CostMethod
    positions: list[PositionOut]
    cash: dict[str, Decimal]
    realised_gain_base: Decimal
    dividend_income_base: Decimal
    net_contributions_base: Decimal
    warnings: list[str]

    @classmethod
    def of(cls, portfolio: PortfolioRecord, state: PortfolioState) -> HoldingsOut:
        positions = [
            PositionOut(
                symbol=key.symbol,
                exchange=key.exchange,
                currency=pos.currency,
                quantity=pos.quantity,
                average_cost=(
                    pos.average_cost.quantize(_EIGHT_DP) if pos.average_cost is not None else None
                ),
                cost_local=pos.cost_local,
                cost_base=pos.cost_base,
                lots=[
                    LotOut(
                        lot_id=lot.lot_id, acquired=lot.acquired, quantity=lot.quantity,
                        cost_local=lot.cost_local, cost_base=lot.cost_base,
                    )
                    for lot in pos.lots
                ],
            )
            for key, pos in sorted(state.positions.items())
        ]
        return cls(
            portfolio_id=portfolio.id,
            base_currency=portfolio.base_currency,
            cost_method=portfolio.cost_method,
            positions=positions,
            cash=dict(sorted(state.cash.items())),
            realised_gain_base=state.realised_gain_base,
            dividend_income_base=state.dividend_income_base,
            net_contributions_base=state.net_contributions_base,
            warnings=state.warnings,
        )


class MappingIn(_In):
    date: str
    type: str
    symbol: str
    quantity: str
    price: str
    fees: str | None = None
    currency: str | None = None
    exchange: str | None = None
    reference: str | None = None
    fx_rate: str | None = None
    date_format: str = "%d/%m/%Y"
    default_exchange: str = "ASX"
    default_currency: Currency = "AUD"
    timezone: str = "Australia/Sydney"

    def to_mapping(self) -> ColumnMapping:
        return ColumnMapping(**self.model_dump())


class ImportIn(_In):
    portfolio_id: UUID
    csv_text: str = Field(min_length=1, max_length=2_000_000)
    mapping: MappingIn | None = None
    commit: bool = False
    file_name: str | None = Field(default=None, max_length=255)


class RowIssueOut(BaseModel):
    line: int
    reason: str
    raw: dict[str, str]

    @classmethod
    def of(cls, issue: RowIssue) -> RowIssueOut:
        return cls(line=issue.line, reason=issue.reason, raw=issue.raw)


class ImportOut(BaseModel):
    committed: int
    mapping: dict[str, Any]
    valid: list[TransactionOut]
    duplicates: list[RowIssueOut]
    errors: list[RowIssueOut]


class AuditOut(BaseModel):
    occurred_at: datetime
    action: str
    entity_type: str
    entity_id: str | None
    detail: dict[str, Any]

    @classmethod
    def of(cls, a: AuditRecord) -> AuditOut:
        return cls(
            occurred_at=a.occurred_at, action=a.action, entity_type=a.entity_type,
            entity_id=a.entity_id, detail=a.detail,
        )

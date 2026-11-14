"""Append-only ledger with duplicate detection, reversals and an audit trail.

Entries are never edited or deleted. A mistake is corrected by reversing the
entry and recording a new one, so the full history stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .engine import PortfolioState, replay
from .models import CostMethod, DuplicateTransaction, LedgerError, Transaction, fingerprint


@dataclass(frozen=True)
class AuditEvent:
    at: datetime
    action: str  # RECORDED | REVERSED
    transaction_id: str
    actor: str
    detail: str


class Ledger:
    def __init__(self, portfolio_id: str, base_currency: str = "AUD") -> None:
        self.portfolio_id = portfolio_id
        self.base_currency = base_currency
        self._entries: list[Transaction] = []
        self._reversed: dict[str, str] = {}  # tx id -> reason
        self.audit: list[AuditEvent] = []

    # -- reads -----------------------------------------------------------
    def all_entries(self) -> list[Transaction]:
        return list(self._entries)

    def active(self) -> list[Transaction]:
        return [tx for tx in self._entries if tx.id not in self._reversed]

    def fingerprints(self) -> set[str]:
        return {fingerprint(tx) for tx in self.active()}

    def state(self, method: CostMethod = CostMethod.FIFO) -> PortfolioState:
        return replay(self.active(), self.base_currency, method)

    # -- writes ----------------------------------------------------------
    def record(
        self,
        tx: Transaction,
        *,
        actor: str = "user",
        source: str = "manual",
        allow_duplicate: bool = False,
    ) -> None:
        if tx.portfolio_id != self.portfolio_id:
            raise LedgerError(f"{tx.id} belongs to portfolio {tx.portfolio_id}")
        if any(e.id == tx.id for e in self._entries):
            raise LedgerError(f"duplicate transaction id: {tx.id}")
        if not allow_duplicate and fingerprint(tx) in self.fingerprints():
            raise DuplicateTransaction(f"{tx.id} matches an existing transaction")
        # Trial replay: reject anything that would break the books (e.g. overselling).
        replay([*self.active(), tx], self.base_currency)
        self._entries.append(tx)
        self._log("RECORDED", tx.id, actor, f"source={source} type={tx.type}")

    def reverse(self, transaction_id: str, reason: str, *, actor: str = "user") -> None:
        if not reason.strip():
            raise LedgerError("a reversal needs a reason")
        if transaction_id in self._reversed:
            raise LedgerError(f"{transaction_id} is already reversed")
        if not any(e.id == transaction_id for e in self._entries):
            raise LedgerError(f"unknown transaction: {transaction_id}")
        remaining = [tx for tx in self.active() if tx.id != transaction_id]
        replay(remaining, self.base_currency)  # e.g. cannot reverse a buy whose shares were sold
        self._reversed[transaction_id] = reason
        self._log("REVERSED", transaction_id, actor, reason)

    def _log(self, action: str, tx_id: str, actor: str, detail: str) -> None:
        self.audit.append(AuditEvent(datetime.now(UTC), action, tx_id, actor, detail))

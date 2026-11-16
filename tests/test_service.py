from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest

from portfolio_api.service import PortfolioService
from portfolio_api.store import Conflict, NotFound
from portfolio_core.models import (
    CostMethod,
    DuplicateTransaction,
    LedgerError,
    SecurityKey,
    Transaction,
    TxType,
)

XYZ = SecurityKey("XYZ", "ASX")
AAPL = SecurityKey("AAPL", "NASDAQ")


def day(n: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n)


def trade(pid, type_, sec, qty, price, n, fee="0", ccy="AUD", fx=None, ref=None):
    return Transaction(
        id=str(uuid4()), portfolio_id=pid, type=type_, trade_date=day(n), currency=ccy,
        security=sec, quantity=D(qty), unit_price=D(price), brokerage_fee=D(fee),
        fx_rate_to_base=D(fx) if fx else None, external_reference=ref,
    )


def deposit(pid, amount, n, ccy="AUD", fx=None):
    return Transaction(
        id=str(uuid4()), portfolio_id=pid, type=TxType.DEPOSIT, trade_date=day(n), currency=ccy,
        amount=D(amount), fx_rate_to_base=D(fx) if fx else None,
    )


@pytest.fixture
def service(store):
    return PortfolioService(store)


@pytest.fixture
def pid(service):
    return service.create_portfolio("Main").id


def test_portfolio_lifecycle(service):
    main = service.create_portfolio("Main", objective="Long term")
    us = service.create_portfolio("US growth", cost_method=CostMethod.AVERAGE)
    with pytest.raises(Conflict):
        service.create_portfolio("Main")
    assert [p.name for p in service.list_portfolios()] == ["Main", "US growth"]
    assert service.get_portfolio(us.id).cost_method is CostMethod.AVERAGE
    assert service.get_portfolio(main.id).objective == "Long term"

    service.archive_portfolio(us.id)
    assert [p.name for p in service.list_portfolios()] == ["Main"]
    assert len(service.list_portfolios(include_archived=True)) == 2
    with pytest.raises(LedgerError, match="archived"):
        service.record_transaction(deposit(us.id, "1", 0))
    with pytest.raises(NotFound):
        service.get_portfolio(str(uuid4()))


def test_prd_examples_survive_persistence(service, pid):
    service.record_transaction(deposit(pid, "2000", 0))
    service.record_transaction(trade(pid, TxType.BUY, XYZ, "100", "10", 1, fee="10"))
    service.record_transaction(trade(pid, TxType.SELL, XYZ, "40", "12", 2, fee="5"))
    _, state = service.holdings(pid)
    pos = state.positions[XYZ]
    assert (pos.quantity, pos.cost_local) == (D("60"), D("606"))
    assert state.realised_gain_base == D("71")
    assert state.cash["AUD"] == D("2000") - 1010 + 475
    assert not state.warnings


def test_usd_trade_keeps_trade_date_fx(service, pid):
    service.record_transaction(
        trade(pid, TxType.BUY, AAPL, "10", "100.12345678", 0, ccy="USD", fx="1.47627383")
    )
    (stored,) = service.list_transactions(pid)
    assert stored.tx.unit_price == D("100.12345678")
    assert stored.tx.fx_rate_to_base == D("1.47627383")
    _, state = service.holdings(pid)
    assert state.positions[AAPL].cost_base == D("1001.2345678") * D("1.47627383")


def test_rejections_write_nothing(service, pid):
    service.record_transaction(trade(pid, TxType.BUY, XYZ, "10", "10", 0))
    bad = [
        (trade(pid, TxType.SELL, XYZ, "11", "10", 1), "only 10"),
        (trade(pid, TxType.BUY, AAPL, "1", "100", 1), "trades in USD"),
        (trade(pid, TxType.BUY, SecurityKey("VOD", "LSE"), "1", "1", 1), "unsupported exchange"),
        (trade(pid, TxType.BUY, XYZ, "1.123456789", "1", 1), "decimal places"),
        (trade(pid, TxType.BUY, AAPL, "1", "100", 1, ccy="USD"), "fx_rate_to_base"),
    ]
    for tx, message in bad:
        with pytest.raises(LedgerError, match=message):
            service.record_transaction(tx)
    assert len(service.list_transactions(pid)) == 1
    assert [a.action for a in service.audit(pid)] == ["PORTFOLIO_CREATED", "TRANSACTION_RECORDED"]


def test_duplicates_blocked_even_across_timezones(service, pid):
    first = trade(pid, TxType.BUY, XYZ, "10", "10", 0)
    service.record_transaction(first)
    sydney = timezone(timedelta(hours=11))
    same_instant = Transaction(
        id=str(uuid4()), portfolio_id=pid, type=TxType.BUY, security=XYZ, currency="AUD",
        trade_date=first.trade_date.astimezone(sydney), quantity=D("10.0"), unit_price=D("10"),
    )
    with pytest.raises(DuplicateTransaction):
        service.record_transaction(same_instant)
    service.record_transaction(same_instant, allow_duplicate=True)
    _, state = service.holdings(pid)
    assert state.positions[XYZ].quantity == D("20")


def test_reversal_is_audited_and_keeps_history(service, pid):
    buy = service.record_transaction(trade(pid, TxType.BUY, XYZ, "10", "10", 0))
    sell = service.record_transaction(trade(pid, TxType.SELL, XYZ, "10", "11", 1))
    with pytest.raises(LedgerError, match="cannot sell"):
        service.reverse_transaction(pid, buy.tx.id, "typo")
    service.reverse_transaction(pid, sell.tx.id, "wrong account")
    with pytest.raises(LedgerError, match="already reversed"):
        service.reverse_transaction(pid, sell.tx.id, "again")

    rows = service.list_transactions(pid)
    assert [(r.active, r.reversed_reason) for r in rows] == [(True, None), (False, "wrong account")]
    _, state = service.holdings(pid)
    assert state.positions[XYZ].quantity == D("10")
    assert service.audit(pid)[-1].action == "TRANSACTION_REVERSED"
    # A reversed entry no longer blocks re-entering the same trade.
    service.record_transaction(trade(pid, TxType.SELL, XYZ, "10", "11", 1))


def test_same_day_entries_keep_insertion_order(service, pid):
    service.record_transaction(trade(pid, TxType.BUY, XYZ, "10", "10", 0))
    service.record_transaction(trade(pid, TxType.SELL, XYZ, "10", "11", 0))
    service.record_transaction(trade(pid, TxType.BUY, XYZ, "5", "12", 0))
    _, state = service.holdings(pid)
    assert state.positions[XYZ].cost_local == D("60")


def test_portfolios_are_isolated(service, pid):
    other = service.create_portfolio("Other").id
    service.record_transaction(trade(pid, TxType.BUY, XYZ, "10", "10", 0))
    assert service.list_transactions(other) == []
    tx_id = service.list_transactions(pid)[0].tx.id
    with pytest.raises(LedgerError, match="not in this portfolio"):
        service.reverse_transaction(other, tx_id, "nope")


CSV = """Trade Date,Side,Symbol,Units,Price,Brokerage,Reference
03/02/2026,Buy,XYZ,100,10.00,3.00,R1
04/02/2026,Sell,XYZ,40,12.50,3.00,R2
05/02/2026,Buy,=CMD(),10,1.00,3.00,R3
"""


def test_csv_import_preview_commit_and_rerun(service, pid):
    preview = service.import_csv(pid, CSV)
    assert preview.committed == 0 and len(preview.preview.valid) == 2
    assert preview.preview.errors[0].line == 4
    assert service.list_transactions(pid) == []

    done = service.import_csv(pid, CSV, commit=True, file_name="stake.csv")
    assert done.committed == 2
    _, state = service.holdings(pid)
    assert state.positions[XYZ].quantity == D("60")

    again = service.import_csv(pid, CSV, commit=True)
    assert again.committed == 0 and len(again.preview.duplicates) == 2
    assert len(service.list_transactions(pid)) == 2
    assert [a.action for a in service.audit(pid)] == ["PORTFOLIO_CREATED", "IMPORT_COMMITTED"]


def test_csv_import_is_all_or_nothing(service, pid):
    text = "Date,Type,Code,Qty,Price\n01/02/2026,B,XYZ,10,1\n02/02/2026,S,XYZ,50,1\n"
    with pytest.raises(LedgerError, match="cannot sell"):
        service.import_csv(pid, text, commit=True)
    assert service.list_transactions(pid) == []
    assert [a.action for a in service.audit(pid)] == ["PORTFOLIO_CREATED"]

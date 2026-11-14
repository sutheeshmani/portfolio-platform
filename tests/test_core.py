from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from portfolio_core.engine import replay
from portfolio_core.importers.csv_import import (
    ColumnMapping,
    commit_import,
    escape_csv_cell,
    preview_import,
    suggest_mapping,
)
from portfolio_core.ledger import Ledger
from portfolio_core.marketdata.alpha_vantage import AlphaVantageProvider
from portfolio_core.marketdata.base import QuoteUnavailable, RateLimited
from portfolio_core.models import (
    CostMethod,
    DuplicateTransaction,
    LedgerError,
    SecurityKey,
    Transaction,
    TxType,
)
from portfolio_core.valuation import FxQuote, PriceType, Quote, value_portfolio

P = "pf1"
XYZ = SecurityKey("XYZ", "ASX")
AAPL = SecurityKey("AAPL", "NASDAQ")


def day(n: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n)


def trade(id_, type_, sec, qty, price, n, fee="0", ccy="AUD", fx=None, ref=None):
    return Transaction(
        id=id_, portfolio_id=P, type=type_, trade_date=day(n), currency=ccy, security=sec,
        quantity=D(qty), unit_price=D(price), brokerage_fee=D(fee),
        fx_rate_to_base=D(fx) if fx else None, external_reference=ref,
    )


def cash(id_, type_, amount, n, ccy="AUD", fx=None, sec=None):
    return Transaction(
        id=id_, portfolio_id=P, type=type_, trade_date=day(n), currency=ccy,
        amount=D(amount), fx_rate_to_base=D(fx) if fx else None, security=sec,
    )


def quote(sec, price, n, ccy="AUD"):
    return Quote(sec, D(price), ccy, day(n), PriceType.EOD, "test")


# --- PRD section 14.3 ------------------------------------------------------

def test_prd_case_1_brokerage_is_in_cost_basis():
    state = replay([trade("b1", TxType.BUY, XYZ, "100", "10", 0, fee="10")], "AUD")
    assert state.positions[XYZ].cost_local == D("1010")
    val = value_portfolio(state, {XYZ: quote(XYZ, "12", 1)}, {}, day(1))
    row = val.holdings[0]
    assert row.market_value_base == D("1200")
    assert row.unrealised_base == D("190")


@pytest.mark.parametrize("method", list(CostMethod))
def test_prd_case_2_partial_sale(method):
    txs = [
        trade("b1", TxType.BUY, XYZ, "100", "10", 0, fee="10"),
        trade("s1", TxType.SELL, XYZ, "40", "12", 1, fee="5"),
    ]
    state = replay(txs, "AUD", method)
    (gain,) = state.realised
    assert gain.cost_local == D("404")
    assert gain.proceeds_local == D("475")
    assert gain.gain_local == D("71")
    pos = state.positions[XYZ]
    assert pos.quantity == D("60")
    assert pos.cost_local == D("606")


# --- lots ------------------------------------------------------------------

def _two_lots():
    return [
        trade("b1", TxType.BUY, XYZ, "100", "10", 0),
        trade("b2", TxType.BUY, XYZ, "100", "20", 1),
        trade("s1", TxType.SELL, XYZ, "150", "30", 2),
    ]


def test_fifo_consumes_oldest_lot_first():
    state = replay(_two_lots(), "AUD", CostMethod.FIFO)
    assert [(g.lot_id, g.quantity, g.cost_local) for g in state.realised] == [
        ("b1", D("100"), D("1000")),
        ("b2", D("50"), D("1000")),
    ]
    assert state.positions[XYZ].cost_local == D("1000")
    assert sum(g.proceeds_local for g in state.realised) == D("4500")


def test_average_spreads_sale_across_lots():
    state = replay(_two_lots(), "AUD", CostMethod.AVERAGE)
    assert sum(g.cost_local for g in state.realised) == D("2250")  # 150 x avg 15
    pos = state.positions[XYZ]
    assert pos.quantity == D("50") and pos.cost_local == D("750")


def test_awkward_fractions_still_reconcile():
    txs = [
        trade("b1", TxType.BUY, XYZ, "3", "10", 0, fee="1"),
        trade("s1", TxType.SELL, XYZ, "1", "11", 1),
        trade("s2", TxType.SELL, XYZ, "2", "11", 2),
    ]
    state = replay(txs, "AUD")
    assert XYZ not in state.positions
    assert sum(g.cost_local for g in state.realised) == D("31")
    assert state.cash["AUD"] == D("2")  # -31 + 11 + 22


def test_full_sale_removes_position_and_books_cash():
    txs = [
        cash("d1", TxType.DEPOSIT, "5000", 0),
        trade("b1", TxType.BUY, XYZ, "100", "10", 1, fee="10"),
        trade("s1", TxType.SELL, XYZ, "100", "12", 2, fee="10"),
        cash("v1", TxType.DIVIDEND, "25", 3, sec=XYZ),
        cash("f1", TxType.FEE, "5", 4),
        cash("w1", TxType.WITHDRAWAL, "1000", 5),
    ]
    state = replay(txs, "AUD")
    assert not state.positions
    assert state.realised_gain_base == D("180")
    assert state.cash["AUD"] == D("5000") - 1010 + 1190 + 25 - 5 - 1000
    assert state.net_contributions_base == D("4000")
    assert state.dividend_income_base == D("25")
    assert not state.warnings


# --- validation ------------------------------------------------------------

def test_cannot_sell_more_than_held():
    with pytest.raises(LedgerError, match="only 10 held"):
        replay(
            [trade("b", TxType.BUY, XYZ, "10", "1", 0), trade("s", TxType.SELL, XYZ, "11", "1", 1)],
            "AUD",
        )


def test_floats_and_naive_dates_are_rejected():
    with pytest.raises(LedgerError, match="Decimal"):
        Transaction(id="x", portfolio_id=P, type=TxType.BUY, trade_date=day(0), currency="AUD",
                    security=XYZ, quantity=1.5, unit_price=D("1"))  # type: ignore[arg-type]
    with pytest.raises(LedgerError, match="timezone"):
        Transaction(id="x", portfolio_id=P, type=TxType.DEPOSIT, currency="AUD",
                    trade_date=datetime(2026, 1, 1), amount=D("1"))


def test_same_ticker_on_two_exchanges_is_two_holdings():
    bhp_us = SecurityKey("BHP", "NYSE")
    bhp_au = SecurityKey("BHP", "ASX")
    state = replay(
        [
            trade("a", TxType.BUY, bhp_au, "10", "40", 0),
            trade("u", TxType.BUY, bhp_us, "5", "50", 0, ccy="USD", fx="1.5"),
        ],
        "AUD",
    )
    assert state.positions[bhp_au].quantity == D("10")
    assert state.positions[bhp_us].quantity == D("5")


def test_foreign_trade_requires_fx_rate():
    with pytest.raises(LedgerError, match="fx_rate_to_base"):
        replay([trade("u", TxType.BUY, AAPL, "1", "100", 0, ccy="USD")], "AUD")


def test_missing_deposit_is_warned_not_hidden():
    state = replay([trade("b", TxType.BUY, XYZ, "1", "10", 0)], "AUD")
    assert state.cash["AUD"] == D("-10") and len(state.warnings) == 1


# --- FX and valuation ------------------------------------------------------

def test_usd_holding_separates_price_and_fx_effects():
    state = replay([trade("u", TxType.BUY, AAPL, "10", "100", 0, ccy="USD", fx="1.5")], "AUD")
    assert state.positions[AAPL].cost_base == D("1500")
    fx = FxQuote("USD", "AUD", D("1.6"), day(5), "test")
    val = value_portfolio(state, {AAPL: quote(AAPL, "110", 5, "USD")}, {"USD": fx}, day(5))
    row = val.holdings[0]
    assert row.market_value_base == D("1760")
    assert row.unrealised_base == D("260")
    assert row.price_effect_base == D("160")
    assert row.fx_effect_base == D("100")
    assert val.cash_base["USD"] == D("-1600")
    assert val.complete


def test_realised_gain_uses_trade_date_fx_on_both_legs():
    state = replay(
        [
            trade("u", TxType.BUY, AAPL, "10", "100", 0, ccy="USD", fx="1.5"),
            trade("s", TxType.SELL, AAPL, "10", "100", 9, ccy="USD", fx="1.6"),
        ],
        "AUD",
    )
    (g,) = state.realised
    assert g.gain_local == D("0") and g.gain_base == D("100")  # pure currency gain


def test_missing_price_is_reported_and_excluded():
    other = SecurityKey("ABC", "ASX")
    state = replay(
        [
            cash("d", TxType.DEPOSIT, "3000", 0),
            trade("a", TxType.BUY, XYZ, "100", "10", 0),
            trade("b", TxType.BUY, other, "100", "10", 0),
        ],
        "AUD",
    )
    val = value_portfolio(state, {XYZ: quote(XYZ, "12", 1)}, {}, day(1))
    assert not val.complete
    assert val.issues == ["MISSING_PRICE ABC:ASX"]
    assert val.holdings_value_base == D("1200")
    missing = next(h for h in val.holdings if h.security == other)
    assert missing.market_value_base is None and not missing.priced
    priced = next(h for h in val.holdings if h.security == XYZ)
    assert priced.weight == D("1200") / D("2200")


def test_stale_price_is_flagged():
    state = replay([trade("a", TxType.BUY, XYZ, "1", "10", 0)], "AUD")
    val = value_portfolio(state, {XYZ: quote(XYZ, "12", 1)}, {}, day(30))
    assert val.holdings[0].stale and val.complete
    assert val.issues[0].startswith("STALE XYZ:ASX")


# --- ledger ----------------------------------------------------------------

def test_ledger_blocks_duplicates_and_audits_reversals():
    ledger = Ledger(P)
    ledger.record(trade("b1", TxType.BUY, XYZ, "100", "10", 0))
    with pytest.raises(DuplicateTransaction):
        ledger.record(trade("b2", TxType.BUY, XYZ, "100", "10", 0))
    ledger.record(trade("s1", TxType.SELL, XYZ, "100", "11", 1))
    with pytest.raises(LedgerError, match="cannot sell"):
        ledger.reverse("b1", "entered twice")  # its shares were sold
    ledger.reverse("s1", "wrong account")
    assert ledger.state().positions[XYZ].quantity == D("100")
    assert [e.action for e in ledger.audit] == ["RECORDED", "RECORDED", "REVERSED"]
    assert len(ledger.all_entries()) == 2  # nothing is ever deleted


def test_ledger_rejects_oversell_without_changing_state():
    ledger = Ledger(P)
    ledger.record(trade("b1", TxType.BUY, XYZ, "10", "10", 0))
    with pytest.raises(LedgerError):
        ledger.record(trade("s1", TxType.SELL, XYZ, "20", "10", 1))
    assert len(ledger.all_entries()) == 1 and len(ledger.audit) == 1


# --- CSV import ------------------------------------------------------------

CSV = """Trade Date,Side,Symbol,Units,Price,Brokerage,Reference
03/02/2026,Buy,XYZ,100,10.00,3.00,R1
04/02/2026,Sell,XYZ,40,"1,012.50",3.00,R2
05/02/2026,Buy,=CMD(),10,1.00,3.00,R3
06/02/2026,Transfer,XYZ,10,1.00,3.00,R4
07/02/2026,Buy,XYZ,ten,1.00,3.00,R5
03/02/2026,Buy,XYZ,100,10.00,3.00,R1
"""


def test_csv_preview_then_commit_is_idempotent():
    import csv as _csv
    import io

    headers = next(_csv.reader(io.StringIO(CSV)))
    mapping = suggest_mapping(headers)
    assert (mapping.date, mapping.quantity, mapping.fees) == ("Trade Date", "Units", "Brokerage")

    ledger = Ledger(P)
    preview = preview_import(CSV, mapping, P, existing_fingerprints=ledger.fingerprints())
    assert [t.external_reference for t in preview.valid] == ["R1", "R2"]
    assert preview.valid[1].unit_price == D("1012.50")
    assert [(e.line, e.reason.split(":")[0]) for e in preview.errors] == [
        (4, "invalid symbol"),
        (5, "unsupported transaction type"),
        (6, "quantity is not a number"),
    ]
    assert [d.line for d in preview.duplicates] == [7]

    assert commit_import(ledger, preview) == 2
    again = preview_import(CSV, mapping, P, existing_fingerprints=ledger.fingerprints())
    assert not again.valid and len(again.duplicates) == 3
    assert ledger.state().positions[XYZ].quantity == D("60")


def test_failed_commit_rolls_back():
    ledger = Ledger(P)
    text = "Date,Type,Code,Qty,Price\n01/02/2026,B,XYZ,10,1\n02/02/2026,S,XYZ,50,1\n"
    preview = preview_import(text, ColumnMapping("Date", "Type", "Code", "Qty", "Price"), P)
    with pytest.raises(LedgerError):
        commit_import(ledger, preview)
    assert not ledger.all_entries() and not ledger.audit


def test_usd_csv_row_needs_fx():
    text = "Date,Type,Code,Qty,Price\n01/02/2026,B,AAPL,1,100\n"
    mapping = ColumnMapping("Date", "Type", "Code", "Qty", "Price",
                            default_exchange="NASDAQ", default_currency="USD")
    assert "no FX rate" in preview_import(text, mapping, P).errors[0].reason


def test_export_escaping():
    assert escape_csv_cell("=SUM(A1)") == "'=SUM(A1)"
    assert escape_csv_cell("BHP") == "BHP"


# --- Alpha Vantage adapter (payload shapes as returned by the API) ----------

def test_alpha_vantage_parsing():
    payloads = {
        "CURRENCY_EXCHANGE_RATE": {"Realtime Currency Exchange Rate": {
            "5. Exchange Rate": "1.47627383", "6. Last Refreshed": "2026-11-14 11:52:04"}},
        "GLOBAL_QUOTE": {"Global Quote": {
            "01. symbol": "AAPL", "05. price": "201.5000", "07. latest trading day": "2026-11-13"}},
    }
    av = AlphaVantageProvider(fetch=lambda p: payloads[p["function"]])
    fx = av.get_fx("USD", "AUD")
    assert fx.rate == D("1.47627383") and fx.as_of == datetime(2026, 11, 14, 11, 52, 4, tzinfo=UTC)
    q = av.get_quote(AAPL)
    assert q.price == D("201.5000") and q.price_type is PriceType.EOD and q.currency == "USD"

    with pytest.raises(QuoteUnavailable):
        av.get_quote(SecurityKey("BHP", "ASX"))
    with pytest.raises(QuoteUnavailable):
        AlphaVantageProvider(fetch=lambda p: {}).get_quote(AAPL)
    with pytest.raises(RateLimited):
        AlphaVantageProvider(fetch=lambda p: {"Information": "25 requests per day"}).get_quote(AAPL)

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest

from portfolio_api.service import PortfolioService
from portfolio_core.marketdata.base import QuoteUnavailable, RateLimited
from portfolio_core.marketdata.eodhd import EodhdProvider, eodhd_ticker
from portfolio_core.marketdata.router import FallbackProvider
from portfolio_core.models import SecurityKey, Transaction, TxType
from portfolio_core.valuation import FxQuote, PriceType, Quote

BHP = SecurityKey("BHP", "ASX")
CBA = SecurityKey("CBA", "ASX")
AAPL = SecurityKey("AAPL", "NASDAQ")
T0 = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 4pm Sydney


def row(code, close, ts=T0):
    # Shape from EODHD's Live (Delayed) docs; numbers arrive as Decimal (parse_float).
    return {"code": code, "timestamp": int(ts.timestamp()), "gmtoffset": 0,
            "close": D(close), "previousClose": D(close), "volume": 1000}


class FakeFetch:
    def __init__(self, rows):
        self.rows = {r["code"]: r for r in rows}
        self.calls = []

    def __call__(self, ticker, params):
        self.calls.append((ticker, dict(params)))
        wanted = [ticker, *params.get("s", "").split(",")] if params.get("s") else [ticker]
        found = [self.rows[t] for t in wanted if t in self.rows]
        if len(wanted) == 1:
            return found[0] if found else {"code": ticker, "timestamp": "NA", "close": "NA"}
        return found


# --- EODHD adapter ---------------------------------------------------------

def test_ticker_mapping():
    assert eodhd_ticker(BHP) == "BHP.AU"
    assert eodhd_ticker(AAPL) == "AAPL.US"
    assert eodhd_ticker(SecurityKey("BRK.B", "NYSE")) == "BRK-B.US"
    with pytest.raises(QuoteUnavailable):
        eodhd_ticker(SecurityKey("VOD", "LSE"))


def test_single_quote_is_delayed_in_listing_currency():
    fetch = FakeFetch([row("BHP.AU", "45.12")])
    q = EodhdProvider(fetch=fetch).get_quote(BHP)
    assert (q.price, q.currency, q.source) == (D("45.12"), "AUD", "eodhd")
    assert q.price_type is PriceType.DELAYED
    assert q.as_of == T0
    assert fetch.calls == [("BHP.AU", {})]


def test_batch_uses_one_request_and_reports_gaps():
    fetch = FakeFetch([row("BHP.AU", "45.12"), row("AAPL.US", "201.5")])
    quotes, missing = EodhdProvider(fetch=fetch).get_quotes(
        [BHP, CBA, AAPL, SecurityKey("VOD", "LSE")]
    )
    assert set(quotes) == {BHP, AAPL} and quotes[AAPL].currency == "USD"
    assert set(missing) == {CBA, SecurityKey("VOD", "LSE")}
    assert len(fetch.calls) == 1 and fetch.calls[0][1]["s"] == "CBA.AU,AAPL.US"


def test_na_values_are_unavailable_not_zero():
    with pytest.raises(QuoteUnavailable):
        EodhdProvider(fetch=FakeFetch([])).get_quote(CBA)


def test_fx():
    fx = EodhdProvider(fetch=FakeFetch([row("USDAUD.FOREX", "1.4763")])).get_fx("USD", "AUD")
    assert (fx.rate, fx.as_of, fx.source) == (D("1.4763"), T0, "eodhd")


def test_fallback_fills_gaps_from_next_provider():
    class Backup:
        name = "backup"

        def get_quote(self, sec):
            if sec == CBA:
                return Quote(sec, D("150"), "AUD", T0, PriceType.EOD, "backup")
            raise QuoteUnavailable("nope")

        def get_fx(self, a, b):
            raise RateLimited("quota")

    router = FallbackProvider([EodhdProvider(fetch=FakeFetch([row("BHP.AU", "45")])), Backup()])
    quotes, missing = router.get_quotes([BHP, CBA, AAPL])
    assert quotes[BHP].source == "eodhd" and quotes[CBA].source == "backup"
    assert "eodhd" in missing[AAPL] and "backup" in missing[AAPL]


# --- refresh and valuation through the service ------------------------------

def tx(pid, type_, n=0, **kw):
    base = dict(id=str(uuid4()), portfolio_id=pid, type=type_, currency="AUD",
                trade_date=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n))
    return Transaction(**{**base, **kw})


@pytest.fixture
def service(store):
    return PortfolioService(store)


@pytest.fixture
def pid(service):
    pid = service.create_portfolio("Main").id
    service.record_transaction(tx(pid, TxType.DEPOSIT, amount=D("5000")))
    service.record_transaction(tx(pid, TxType.BUY, 1, security=BHP, quantity=D("100"),
                                  unit_price=D("40"), brokerage_fee=D("10")))
    service.record_transaction(tx(pid, TxType.BUY, 1, security=CBA, quantity=D("10"),
                                  unit_price=D("100")))
    service.record_transaction(tx(pid, TxType.DEPOSIT, 2, currency="USD", amount=D("2000"),
                                  fx_rate_to_base=D("1.5")))
    service.record_transaction(tx(pid, TxType.BUY, 3, currency="USD", security=AAPL,
                                  quantity=D("5"), unit_price=D("200"),
                                  fx_rate_to_base=D("1.5")))
    return pid


def test_valuation_before_any_refresh_reports_everything_missing(service, pid):
    _, v = service.valuation(pid, as_of=T0)
    assert not v.complete and v.holdings_value_base == 0
    assert "MISSING_PRICE AAPL:NASDAQ" in v.issues and any("MISSING_FX USD" in i for i in v.issues)


def test_refresh_then_value_in_aud(service, pid):
    provider = EodhdProvider(fetch=FakeFetch([
        row("BHP.AU", "45"), row("CBA.AU", "150"), row("AAPL.US", "210"),
        row("USDAUD.FOREX", "1.6"),
    ]))
    result = service.refresh_prices(pid, provider)
    assert not result.missing and set(result.fx) == {"USD"}

    _, v = service.valuation(pid, as_of=T0 + timedelta(minutes=20))
    assert v.complete and not v.issues
    assert v.holdings_value_base == D("4500") + D("1500") + D("1050") * D("1.6")
    # AUD cash: 5000 - 4010 - 1000 ; USD cash: 2000 - 1000, valued at 1.6
    assert v.cash_value_base == D("-10") + D("1000") * D("1.6")
    aapl = next(h for h in v.holdings if h.security == AAPL)
    assert aapl.cost_base == D("1500") and aapl.fx_effect_base == D("100")
    assert aapl.quote.price_type is PriceType.DELAYED
    assert service.audit(pid)[-1].action == "PRICES_REFRESHED"


def test_partial_refresh_keeps_older_prices_and_flags_staleness(service, pid):
    old = T0 - timedelta(days=10)
    service.refresh_prices(pid, EodhdProvider(fetch=FakeFetch([
        row("BHP.AU", "44", old), row("CBA.AU", "149", old), row("AAPL.US", "205", old),
        row("USDAUD.FOREX", "1.55", old),
    ])))
    result = service.refresh_prices(pid, EodhdProvider(fetch=FakeFetch([
        row("BHP.AU", "45"), row("USDAUD.FOREX", "1.6"),
    ])))
    assert set(result.missing) == {CBA, AAPL}

    _, v = service.valuation(pid, as_of=T0)
    prices = {h.security: (h.quote.price, h.stale) for h in v.holdings}
    assert prices[BHP] == (D("45"), False)
    assert prices[CBA] == (D("149"), True)
    assert v.complete and any(i.startswith("STALE CBA:ASX") for i in v.issues)


def test_stored_fx_is_used_for_cash_even_without_holdings(service):
    pid = service.create_portfolio("Cash only").id
    service.record_transaction(tx(pid, TxType.DEPOSIT, currency="USD", amount=D("100"),
                                  fx_rate_to_base=D("1.5")))
    service.store.save_fx(FxQuote("USD", "AUD", D("1.6"), T0, "test"))
    _, v = service.valuation(pid, as_of=T0)
    assert v.total_value_base == D("160") and v.complete

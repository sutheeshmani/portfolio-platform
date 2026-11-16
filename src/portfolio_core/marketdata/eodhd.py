"""EODHD adapter: ASX and US equities, plus FX.

Uses the Live (Delayed) endpoint, ``/api/real-time/{TICKER}``. Per EODHD's
documentation (checked 16 Nov 2026):

* stock quotes are delayed 15-20 minutes, so they are labelled DELAYED, never live;
* ``timestamp`` is Unix seconds in UTC;
* ASX tickers carry ``.AU``, US tickers ``.US``, FX pairs ``.FOREX`` (e.g. USDAUD.FOREX);
* several tickers can share one request via ``s=``; the response is then a list;
* the free plan allows 20 API calls a day, so callers must store results and
  refresh sparingly. Whether a multi-ticker request counts as one call or one
  per ticker is not stated consistently in the docs.

The quote carries no currency, so the security's listing currency is used
(AUD for ASX, USD for US exchanges).

JSON is parsed with ``Decimal`` so prices never pass through binary floats.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models import SecurityKey
from ..valuation import FxQuote, PriceType, Quote
from .base import MarketDataError, QuoteUnavailable, RateLimited

# (path ticker, query params) -> decoded JSON
Fetch = Callable[[str, Mapping[str, str]], Any]

_BASE_URL = "https://eodhd.com/api/real-time/"
_SUFFIX = {"ASX": ("AU", "AUD"), "NASDAQ": ("US", "USD"), "NYSE": ("US", "USD")}


def _http_fetch(api_key: str) -> Fetch:
    def fetch(ticker: str, params: Mapping[str, str]) -> Any:
        query = urllib.parse.urlencode({**params, "api_token": api_key, "fmt": "json"})
        url = f"{_BASE_URL}{urllib.parse.quote(ticker)}?{query}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
                return json.loads(resp.read(), parse_float=Decimal)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited("EODHD rate or daily call limit reached") from exc
            if exc.code in (401, 403):
                raise QuoteUnavailable(f"EODHD refused {ticker} (HTTP {exc.code})") from exc
            if exc.code == 404:
                raise QuoteUnavailable(f"EODHD has no ticker {ticker}") from exc
            raise MarketDataError(f"EODHD HTTP {exc.code}") from exc

    return fetch


def eodhd_ticker(security: SecurityKey) -> str:
    try:
        suffix, _ = _SUFFIX[security.exchange]
    except KeyError:
        raise QuoteUnavailable(f"EODHD adapter does not map {security.exchange}") from None
    # EODHD writes share classes with a hyphen (BRK-B.US); some brokers use a dot.
    return f"{security.symbol.replace('.', '-')}.{suffix}"


def _number(value: object) -> Decimal | None:
    """EODHD sends 'NA' (a string) when it has no value."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    return None


def _stamp(row: Mapping[str, Any]) -> datetime | None:
    ts = row.get("timestamp")
    if isinstance(ts, Decimal):
        ts = int(ts)
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


class EodhdProvider:
    name = "eodhd"

    def __init__(self, api_key: str = "", *, fetch: Fetch | None = None) -> None:
        if fetch is None and not api_key:
            raise ValueError("api_key is required")
        self._fetch = fetch or _http_fetch(api_key)

    def _rows(self, tickers: Sequence[str]) -> dict[str, Mapping[str, Any]]:
        params = {"s": ",".join(tickers[1:])} if len(tickers) > 1 else {}
        data = self._fetch(tickers[0], params)
        rows = data if isinstance(data, list) else [data]
        out: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if isinstance(row, Mapping) and isinstance(row.get("code"), str):
                out[row["code"].upper()] = row
        return out

    def _quote(self, security: SecurityKey, row: Mapping[str, Any] | None) -> Quote:
        price = _number(row.get("close")) if row else None
        stamp = _stamp(row) if row else None
        if row is None or price is None or price <= 0 or stamp is None:
            raise QuoteUnavailable(f"EODHD returned no usable quote for {security}")
        return Quote(
            security=security,
            price=price,
            currency=_SUFFIX[security.exchange][1],
            as_of=stamp,
            price_type=PriceType.DELAYED,
            source=self.name,
        )

    def get_quote(self, security: SecurityKey) -> Quote:
        ticker = eodhd_ticker(security)
        return self._quote(security, self._rows([ticker]).get(ticker))

    def get_quotes(
        self, securities: Sequence[SecurityKey]
    ) -> tuple[dict[SecurityKey, Quote], dict[SecurityKey, str]]:
        """One request for many securities. Returns (quotes, reasons for the ones missing)."""
        quotes: dict[SecurityKey, Quote] = {}
        missing: dict[SecurityKey, str] = {}
        mapped: dict[str, SecurityKey] = {}
        for sec in securities:
            try:
                mapped[eodhd_ticker(sec)] = sec
            except QuoteUnavailable as exc:
                missing[sec] = str(exc)
        if mapped:
            rows = self._rows(list(mapped))
            for ticker, sec in mapped.items():
                try:
                    quotes[sec] = self._quote(sec, rows.get(ticker))
                except QuoteUnavailable as exc:
                    missing[sec] = str(exc)
        return quotes, missing

    def get_fx(self, from_currency: str, to_currency: str) -> FxQuote:
        ticker = f"{from_currency}{to_currency}.FOREX"
        row = self._rows([ticker]).get(ticker)
        rate = _number(row.get("close")) if row else None
        stamp = _stamp(row) if row else None
        if rate is None or rate <= 0 or stamp is None:
            raise QuoteUnavailable(f"EODHD returned no FX rate for {ticker}")
        return FxQuote(from_currency, to_currency, rate, stamp, self.name)

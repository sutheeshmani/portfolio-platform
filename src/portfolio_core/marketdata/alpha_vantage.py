"""Alpha Vantage adapter (US equities and FX).

Checked on 2026-11-14 with a free key:
* USD->AUD ``CURRENCY_EXCHANGE_RATE`` works.
* ``GLOBAL_QUOTE`` for ``BHP.AX`` returned an empty body and ``SYMBOL_SEARCH``
  listed no ASX line for BHP, so ASX prices need a second provider. This adapter
  raises ``QuoteUnavailable`` rather than guessing.
* The free tier allows 25 requests a day, so results must be cached.

GLOBAL_QUOTE gives the latest trading day's price, so quotes are labelled EOD,
never live.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models import SecurityKey
from ..valuation import FxQuote, PriceType, Quote
from .base import MarketDataError, QuoteUnavailable, RateLimited

Fetch = Callable[[Mapping[str, str]], dict[str, Any]]

_US_EXCHANGES = {"NASDAQ", "NYSE", "ARCA", "AMEX"}
_BASE_URL = "https://www.alphavantage.co/query"


def _http_fetch(api_key: str) -> Fetch:
    def fetch(params: Mapping[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "apikey": api_key})
        with urllib.request.urlopen(f"{_BASE_URL}?{query}", timeout=15) as resp:  # noqa: S310
            data = json.load(resp)
        if not isinstance(data, dict):
            raise MarketDataError("unexpected response")
        return data

    return fetch


class AlphaVantageProvider:
    name = "alpha_vantage"

    def __init__(self, api_key: str = "", *, fetch: Fetch | None = None) -> None:
        if fetch is None and not api_key:
            raise ValueError("api_key is required")
        self._fetch = fetch or _http_fetch(api_key)

    def _call(self, params: Mapping[str, str]) -> dict[str, Any]:
        data = self._fetch(params)
        if "Note" in data or "Information" in data or "error" in data:
            raise RateLimited(str(data.get("Note") or data.get("Information") or data["error"]))
        if "Error Message" in data:
            raise QuoteUnavailable(str(data["Error Message"]))
        return data

    def get_quote(self, security: SecurityKey) -> Quote:
        if security.exchange not in _US_EXCHANGES:
            raise QuoteUnavailable(f"{self.name} does not cover {security.exchange}")
        data = self._call({"function": "GLOBAL_QUOTE", "symbol": security.symbol})
        body = data.get("Global Quote") or {}
        try:
            price = Decimal(body["05. price"])
            day = datetime.strptime(body["07. latest trading day"], "%Y-%m-%d")
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise QuoteUnavailable(f"no quote for {security}") from exc
        return Quote(
            security=security,
            price=price,
            currency="USD",
            as_of=day.replace(tzinfo=UTC),
            price_type=PriceType.EOD,
            source=self.name,
        )

    def get_fx(self, from_currency: str, to_currency: str) -> FxQuote:
        data = self._call(
            {
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": from_currency,
                "to_currency": to_currency,
            }
        )
        body = data.get("Realtime Currency Exchange Rate") or {}
        try:
            rate = Decimal(body["5. Exchange Rate"])
            stamp = datetime.strptime(body["6. Last Refreshed"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise QuoteUnavailable(f"no FX rate {from_currency}->{to_currency}") from exc
        return FxQuote(from_currency, to_currency, rate, stamp.replace(tzinfo=UTC), self.name)

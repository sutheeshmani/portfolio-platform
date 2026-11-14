"""Provider abstraction. Every adapter returns the same timestamped, sourced types."""

from __future__ import annotations

from typing import Protocol

from ..models import SecurityKey
from ..valuation import FxQuote, Quote


class MarketDataError(RuntimeError):
    pass


class QuoteUnavailable(MarketDataError):
    """The provider has no data for this security or currency pair."""


class RateLimited(MarketDataError):
    pass


class MarketDataProvider(Protocol):
    name: str

    def get_quote(self, security: SecurityKey) -> Quote: ...

    def get_fx(self, from_currency: str, to_currency: str) -> FxQuote: ...

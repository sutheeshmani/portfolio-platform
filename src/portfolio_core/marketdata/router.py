"""Try providers in order until one answers. Each result keeps its own ``source``."""

from __future__ import annotations

from collections.abc import Sequence

from ..models import SecurityKey
from ..valuation import FxQuote, Quote
from .base import MarketDataError, MarketDataProvider, QuoteUnavailable, RateLimited


class FallbackProvider:
    name = "fallback"

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = list(providers)

    def get_quote(self, security: SecurityKey) -> Quote:
        errors: list[str] = []
        for p in self.providers:
            try:
                return p.get_quote(security)
            except (QuoteUnavailable, RateLimited) as exc:
                errors.append(f"{p.name}: {exc}")
        raise QuoteUnavailable("; ".join(errors))

    def get_quotes(
        self, securities: Sequence[SecurityKey]
    ) -> tuple[dict[SecurityKey, Quote], dict[SecurityKey, str]]:
        """Batch where a provider supports it; anything it misses goes to the next one."""
        quotes: dict[SecurityKey, Quote] = {}
        reasons: dict[SecurityKey, list[str]] = {s: [] for s in securities}
        pending = list(securities)
        for p in self.providers:
            if not pending:
                break
            batch = getattr(p, "get_quotes", None)
            if callable(batch):
                try:
                    got, why = batch(pending)
                except (QuoteUnavailable, RateLimited) as exc:
                    got, why = {}, {s: str(exc) for s in pending}
                quotes.update(got)
                for sec, reason in why.items():
                    reasons[sec].append(f"{p.name}: {reason}")
            else:
                for sec in pending:
                    try:
                        quotes[sec] = p.get_quote(sec)
                    except (QuoteUnavailable, RateLimited) as exc:
                        reasons[sec].append(f"{p.name}: {exc}")
            pending = [s for s in pending if s not in quotes]
        return quotes, {s: "; ".join(reasons[s]) or "no provider" for s in pending}

    def get_fx(self, from_currency: str, to_currency: str) -> FxQuote:
        errors: list[str] = []
        for p in self.providers:
            try:
                return p.get_fx(from_currency, to_currency)
            except (QuoteUnavailable, RateLimited) as exc:
                errors.append(f"{p.name}: {exc}")
        raise MarketDataError("; ".join(errors))

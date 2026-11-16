"""HTTP layer. Thin by design: validate, call the service, shape the response."""

import dataclasses
import hmac
from collections.abc import Callable, Iterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from portfolio_core.marketdata.base import MarketDataProvider
from portfolio_core.models import DuplicateTransaction, LedgerError

from .schemas import (
    AuditOut,
    HoldingsOut,
    ImportIn,
    ImportOut,
    PortfolioIn,
    PortfolioOut,
    RefreshOut,
    ReversalIn,
    RowIssueOut,
    TransactionIn,
    TransactionOut,
    ValuationOut,
)
from .service import PortfolioService
from .store import Conflict, NotFound, Store

StoreDependency = Callable[[], Iterator[Store]]
MIN_TOKEN_LENGTH = 32


def create_app(
    get_store: StoreDependency,
    api_token: str,
    provider: MarketDataProvider | None = None,
) -> FastAPI:
    """Build the app. ``get_store`` yields one store per request.

    Authentication is a single static bearer token for now. It is a stand-in
    until the identity provider (Auth0 or Entra) with MFA is wired in.
    """
    if len(api_token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"API token must be at least {MIN_TOKEN_LENGTH} characters")
    expected = api_token.encode()

    app = FastAPI(title="Portfolio platform API", version="0.2.0")
    bearer = HTTPBearer(auto_error=False)

    def require_auth(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        supplied = credentials.credentials.encode() if credentials else b""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def get_service(store: Annotated[Store, Depends(get_store)]) -> PortfolioService:
        return PortfolioService(store)

    Service = Annotated[PortfolioService, Depends(get_service)]

    def _error(code: int) -> Callable[[Request, Exception], JSONResponse]:
        def handler(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=code)

        return handler

    # Most specific first: DuplicateTransaction is a LedgerError.
    app.add_exception_handler(NotFound, _error(status.HTTP_404_NOT_FOUND))
    app.add_exception_handler(Conflict, _error(status.HTTP_409_CONFLICT))
    app.add_exception_handler(DuplicateTransaction, _error(status.HTTP_409_CONFLICT))
    app.add_exception_handler(LedgerError, _error(422))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])

    # -- portfolios ------------------------------------------------------
    @api.post("/portfolios", status_code=status.HTTP_201_CREATED)
    def create_portfolio(body: PortfolioIn, service: Service) -> PortfolioOut:
        return PortfolioOut.of(
            service.create_portfolio(
                body.name, body.base_currency, body.cost_method, body.objective
            )
        )

    @api.get("/portfolios")
    def list_portfolios(service: Service, include_archived: bool = False) -> list[PortfolioOut]:
        rows = service.list_portfolios(include_archived=include_archived)
        return [PortfolioOut.of(p) for p in rows]

    @api.get("/portfolios/{portfolio_id}")
    def get_portfolio(portfolio_id: UUID, service: Service) -> PortfolioOut:
        return PortfolioOut.of(service.get_portfolio(str(portfolio_id)))

    @api.delete("/portfolios/{portfolio_id}")
    def archive_portfolio(portfolio_id: UUID, service: Service) -> PortfolioOut:
        """Archives the portfolio. Nothing is deleted."""
        return PortfolioOut.of(service.archive_portfolio(str(portfolio_id)))

    @api.get("/portfolios/{portfolio_id}/holdings")
    def holdings(portfolio_id: UUID, service: Service) -> HoldingsOut:
        portfolio, state = service.holdings(str(portfolio_id))
        return HoldingsOut.of(portfolio, state)

    @api.get("/portfolios/{portfolio_id}/valuation")
    def valuation(portfolio_id: UUID, service: Service) -> ValuationOut:
        """Values holdings from stored prices. Run a price refresh first to update them."""
        portfolio, val = service.valuation(str(portfolio_id))
        _, state = service.holdings(str(portfolio_id))
        return ValuationOut.of(portfolio, val, state.net_contributions_base)

    @api.post("/portfolios/{portfolio_id}/prices/refresh")
    def refresh_prices(portfolio_id: UUID, service: Service) -> RefreshOut:
        """Fetches prices and FX for current holdings. Each call spends provider API quota."""
        if provider is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "no market data provider is configured"
            )
        return RefreshOut.of(service.refresh_prices(str(portfolio_id), provider))

    @api.get("/portfolios/{portfolio_id}/audit")
    def audit(portfolio_id: UUID, service: Service) -> list[AuditOut]:
        return [AuditOut.of(a) for a in service.audit(str(portfolio_id))]

    # -- transactions ----------------------------------------------------
    @api.post("/transactions", status_code=status.HTTP_201_CREATED)
    def create_transaction(body: TransactionIn, service: Service) -> TransactionOut:
        tx = body.to_transaction(str(uuid4()))
        stored = service.record_transaction(tx, allow_duplicate=body.allow_duplicate)
        return TransactionOut.of(stored)

    @api.get("/transactions")
    def list_transactions(
        portfolio_id: UUID, service: Service, include_reversed: bool = True
    ) -> list[TransactionOut]:
        rows = service.list_transactions(str(portfolio_id))
        return [TransactionOut.of(s) for s in rows if include_reversed or s.active]

    @api.post("/transactions/{transaction_id}/reverse", status_code=status.HTTP_204_NO_CONTENT)
    def reverse_transaction(transaction_id: UUID, body: ReversalIn, service: Service) -> None:
        """Corrections are a reversal plus a new entry; entries are never edited."""
        service.reverse_transaction(str(body.portfolio_id), str(transaction_id), body.reason)

    @api.post("/transactions/import")
    def import_transactions(body: ImportIn, service: Service) -> ImportOut:
        """Preview by default. Send ``commit: true`` to write the valid rows."""
        result = service.import_csv(
            str(body.portfolio_id),
            body.csv_text,
            mapping=body.mapping.to_mapping() if body.mapping else None,
            commit=body.commit,
            file_name=body.file_name,
        )
        return ImportOut(
            committed=result.committed,
            mapping=dataclasses.asdict(result.mapping),
            valid=[TransactionOut.of_tx(tx) for tx in result.preview.valid],
            duplicates=[RowIssueOut.of(i) for i in result.preview.duplicates],
            errors=[RowIssueOut.of(i) for i in result.preview.errors],
        )

    app.include_router(api)
    return app

# Portfolio platform

Personal ASX + US portfolio manager. This repo currently holds the Phase 1 back end:
the transaction ledger and calculation engine (`portfolio_core`), and the REST API
with PostgreSQL persistence on top of it (`portfolio_api`).

## What is here

| Path | Purpose |
| --- | --- |
| `src/portfolio_core/models.py` | Transaction and exchange-aware security types; Decimal-only validation; duplicate fingerprint |
| `src/portfolio_core/engine.py` | Replays the ledger into lots, positions, cash, realised P&L and dividends (FIFO or average cost) |
| `src/portfolio_core/ledger.py` | Append-only ledger with duplicate blocking, reversals and an audit trail |
| `src/portfolio_core/valuation.py` | AUD valuation with sourced, timestamped prices and FX; flags missing and stale data; splits price and FX effects |
| `src/portfolio_core/importers/csv_import.py` | Column-mapped CSV import: validate, de-duplicate, preview, all-or-nothing commit |
| `src/portfolio_core/marketdata/` | Provider interface; EODHD (ASX, US, FX), Alpha Vantage (US, FX) and a fallback router |
| `src/portfolio_api/service.py` | The only writer to the ledger: lock, re-check with the engine, append, audit |
| `src/portfolio_api/store.py`, `store_postgres.py` | Storage interface, in-memory store, PostgreSQL store (psycopg 3) |
| `src/portfolio_api/app.py`, `schemas.py` | FastAPI routes and request/response models |
| `db/migrations/` | PostgreSQL schema; the ledger table is append-only by trigger |
| `tests/` | Core tests include both worked examples from PRD 14.3; service and API tests run against both stores |

`portfolio_core` has no third-party runtime dependencies.

## Run it

```bash
pip install -e ".[api,dev]"
for f in db/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f "$f"; done

export DATABASE_URL=postgresql://user:pass@localhost:5432/portfolio
export API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export EODHD_API_KEY=...          # free key from eodhd.com; covers ASX
export ALPHAVANTAGE_API_KEY=...   # optional backup for US quotes and FX
uvicorn portfolio_api.main:build --factory     # docs at http://localhost:8000/docs

pytest -q            # Postgres tests run when DATABASE_URL is set, otherwise they skip
ruff check . && mypy
```

## API (`/api/v1`, bearer token required)

| Method | Path | Purpose |
| --- | --- | --- |
| POST, GET | `/portfolios` | Create, list |
| GET, DELETE | `/portfolios/{id}` | Read, archive (nothing is deleted) |
| GET | `/portfolios/{id}/holdings` | Positions, lots, cash and realised P&L derived from the ledger |
| GET | `/portfolios/{id}/valuation` | Value in base currency from stored prices, with sources, timestamps and missing/stale flags |
| POST | `/portfolios/{id}/prices/refresh` | Fetch quotes and FX for current holdings (spends provider quota) |
| GET | `/portfolios/{id}/audit` | Audit trail |
| POST, GET | `/transactions` | Record, list |
| POST | `/transactions/{id}/reverse` | Reverse an entry with a reason |
| POST | `/transactions/import` | CSV preview; `commit: true` writes the valid rows |

Decimal values are sent and returned as JSON strings. JSON floats are rejected.

## Rules the code enforces

- The ledger is the source of truth. Holdings are derived by `replay`, never edited.
- No floats. A float in a transaction raises `LedgerError`.
- A ticker is never unique on its own: `BHP:ASX` and `BHP:NYSE` are different securities.
- A foreign-currency trade must carry its trade-date FX rate. That rate is kept for the
  cost base; current FX is only used for valuation.
- A missing price is reported and left out of the totals (`complete` is false). A stale
  price is used but flagged.
- Entries are reversed, not edited or deleted.

## Known gaps

- **Market data quota.** EODHD is the ASX source (Alpha Vantage has no ASX
  listings). Its free plan allows 20 API calls a day, so prices are stored and
  only fetched on an explicit refresh; valuation never calls a provider.
  Quotes are 15-20 minutes delayed and labelled DELAYED. The EODHD adapter is
  tested against the documented response format, not yet against a live key.
- **Stake preset.** `suggest_mapping` guesses columns from common header names.
  It has not been checked against a real Stake export.
- **Tax.** FIFO and average cost are accounting views, not an ATO CGT calculation.
- **Auth.** The API uses one static bearer token. It is a stand-in until an
  identity provider (Auth0 or Entra) with MFA is chosen.
- Not yet built: scheduled price refresh, daily movement (previous close),
  rate limiting, splits
  and other corporate actions, currency conversions between cash balances,
  time-weighted returns, the Next.js front end.

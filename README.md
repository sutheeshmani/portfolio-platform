# Portfolio platform

Personal ASX + US portfolio manager. This repo currently holds the Phase 1 core:
the transaction ledger and the calculation engine that everything else will sit on.

## What is here

| Path | Purpose |
| --- | --- |
| `src/portfolio_core/models.py` | Transaction and exchange-aware security types; Decimal-only validation; duplicate fingerprint |
| `src/portfolio_core/engine.py` | Replays the ledger into lots, positions, cash, realised P&L and dividends (FIFO or average cost) |
| `src/portfolio_core/ledger.py` | Append-only ledger with duplicate blocking, reversals and an audit trail |
| `src/portfolio_core/valuation.py` | AUD valuation with sourced, timestamped prices and FX; flags missing and stale data; splits price and FX effects |
| `src/portfolio_core/importers/csv_import.py` | Column-mapped CSV import: validate, de-duplicate, preview, all-or-nothing commit |
| `src/portfolio_core/marketdata/` | Provider interface and the Alpha Vantage adapter (US equities and FX) |
| `db/migrations/0001_core_schema.sql` | PostgreSQL schema; the ledger table is append-only by trigger |
| `tests/test_core.py` | Includes both worked examples from PRD section 14.3 |

The core has no third-party runtime dependencies.

## Run it

```bash
pip install -e ".[dev]"
pytest -q
ruff check . && mypy
psql -v ON_ERROR_STOP=1 -d <database> -f db/migrations/0001_core_schema.sql
```

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

- **ASX prices.** Alpha Vantage returned nothing for `BHP.AX` on a free key
  (checked 14 Nov 2026), and the free tier is 25 requests a day. A second
  provider is needed for ASX; the adapter raises `QuoteUnavailable` for it.
- **Stake preset.** `suggest_mapping` guesses columns from common header names.
  It has not been checked against a real Stake export.
- **Tax.** FIFO and average cost are accounting views, not an ATO CGT calculation.
- Not yet built: FastAPI layer, database persistence for the ledger, auth,
  splits and other corporate actions, currency conversions between cash
  balances, time-weighted returns, the Next.js front end.

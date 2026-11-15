-- Stable ordering for entries that share a trade date (rows inserted in one
-- database transaction also share created_at), plus a duplicate-lookup index.

BEGIN;

ALTER TABLE ledger_transaction
    ADD COLUMN ledger_seq BIGINT GENERATED ALWAYS AS IDENTITY;

CREATE UNIQUE INDEX ledger_transaction_seq ON ledger_transaction (ledger_seq);

DROP INDEX ledger_transaction_portfolio_date;
CREATE INDEX ledger_transaction_portfolio_date
    ON ledger_transaction (portfolio_id, trade_date, ledger_seq);

CREATE INDEX ledger_transaction_fingerprint
    ON ledger_transaction (portfolio_id, fingerprint);

CREATE INDEX audit_event_portfolio ON audit_event ((detail ->> 'portfolio_id'), occurred_at);

COMMIT;

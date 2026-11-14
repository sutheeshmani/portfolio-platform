-- Core schema for Phase 1: security master, ledger, lots, prices, FX, audit.
-- Money and quantities are NUMERIC(24,8); nothing is stored as float.
-- Holdings are derived from the ledger by the calculation engine. The holding
-- and tax_lot tables are caches that reconciliation can rebuild at any time.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE app_user (
    user_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          VARCHAR(320) NOT NULL UNIQUE,
    base_currency  CHAR(3) NOT NULL DEFAULT 'AUD',
    timezone       VARCHAR(64) NOT NULL DEFAULT 'Australia/Sydney',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exchange (
    exchange_code  VARCHAR(32) PRIMARY KEY,
    name           VARCHAR(128) NOT NULL,
    country_code   CHAR(2) NOT NULL,
    currency_code  CHAR(3) NOT NULL,
    timezone       VARCHAR(64) NOT NULL
);

INSERT INTO exchange VALUES
    ('ASX',    'Australian Securities Exchange', 'AU', 'AUD', 'Australia/Sydney'),
    ('NASDAQ', 'Nasdaq Stock Market',            'US', 'USD', 'America/New_York'),
    ('NYSE',   'New York Stock Exchange',        'US', 'USD', 'America/New_York');

CREATE TABLE security (
    security_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol         VARCHAR(32) NOT NULL,
    company_name   VARCHAR(255) NOT NULL,
    exchange_code  VARCHAR(32) NOT NULL REFERENCES exchange,
    currency_code  CHAR(3) NOT NULL,
    asset_type     VARCHAR(32) NOT NULL CHECK (asset_type IN ('EQUITY', 'ETF', 'REIT')),
    isin           VARCHAR(32),
    sector         VARCHAR(128),
    country_code   CHAR(2),
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (symbol, exchange_code)
);

CREATE TABLE portfolio (
    portfolio_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_user,
    portfolio_name  VARCHAR(128) NOT NULL,
    base_currency   CHAR(3) NOT NULL DEFAULT 'AUD',
    -- Real portfolios only. Paper trading gets its own tables and service (PRD 10.5).
    portfolio_type  VARCHAR(32) NOT NULL DEFAULT 'REAL' CHECK (portfolio_type = 'REAL'),
    cost_method     VARCHAR(16) NOT NULL DEFAULT 'FIFO' CHECK (cost_method IN ('FIFO', 'AVERAGE')),
    objective       TEXT,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, portfolio_name)
);

CREATE TABLE import_batch (
    import_batch_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id     UUID NOT NULL REFERENCES portfolio,
    source           VARCHAR(64) NOT NULL,
    file_name        VARCHAR(255),
    file_sha256      CHAR(64),
    rows_valid       INTEGER NOT NULL DEFAULT 0,
    rows_duplicate   INTEGER NOT NULL DEFAULT 0,
    rows_rejected    INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only. Corrections are made with ledger_reversal plus a new row.
CREATE TABLE ledger_transaction (
    transaction_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID NOT NULL REFERENCES portfolio,
    security_id         UUID REFERENCES security,
    transaction_type    VARCHAR(32) NOT NULL
        CHECK (transaction_type IN ('BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'FEE')),
    trade_date          TIMESTAMPTZ NOT NULL,
    settlement_date     DATE,
    quantity            NUMERIC(24,8) CHECK (quantity > 0),
    unit_price          NUMERIC(24,8) CHECK (unit_price > 0),
    amount              NUMERIC(24,8) CHECK (amount > 0),
    currency_code       CHAR(3) NOT NULL,
    fx_rate_to_base     NUMERIC(24,8) CHECK (fx_rate_to_base > 0),
    brokerage_fee       NUMERIC(24,8) NOT NULL DEFAULT 0 CHECK (brokerage_fee >= 0),
    other_fees          NUMERIC(24,8) NOT NULL DEFAULT 0 CHECK (other_fees >= 0),
    external_reference  VARCHAR(128),
    fingerprint         CHAR(64) NOT NULL,
    import_batch_id     UUID REFERENCES import_batch,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (transaction_type IN ('BUY', 'SELL')
            AND security_id IS NOT NULL AND quantity IS NOT NULL
            AND unit_price IS NOT NULL AND amount IS NULL)
        OR
        (transaction_type NOT IN ('BUY', 'SELL')
            AND amount IS NOT NULL AND quantity IS NULL AND unit_price IS NULL)
    )
);

CREATE INDEX ledger_transaction_portfolio_date
    ON ledger_transaction (portfolio_id, trade_date, created_at);

CREATE TABLE ledger_reversal (
    transaction_id  UUID PRIMARY KEY REFERENCES ledger_transaction,
    reason          TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    reversed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION ledger_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ledger_transaction is append-only; reverse the entry instead';
END $$;

CREATE TRIGGER ledger_transaction_no_update
    BEFORE UPDATE OR DELETE ON ledger_transaction
    FOR EACH ROW EXECUTE FUNCTION ledger_is_append_only();

-- Derived caches, rebuilt from the ledger.
CREATE TABLE tax_lot (
    tax_lot_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID NOT NULL REFERENCES portfolio,
    security_id         UUID NOT NULL REFERENCES security,
    buy_transaction_id  UUID NOT NULL REFERENCES ledger_transaction,
    acquired_at         TIMESTAMPTZ NOT NULL,
    quantity_remaining  NUMERIC(24,8) NOT NULL CHECK (quantity_remaining >= 0),
    cost_local          NUMERIC(24,8) NOT NULL,
    cost_base           NUMERIC(24,8) NOT NULL
);

CREATE TABLE holding (
    holding_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id    UUID NOT NULL REFERENCES portfolio,
    security_id     UUID NOT NULL REFERENCES security,
    quantity        NUMERIC(24,8) NOT NULL,
    average_cost    NUMERIC(24,8),
    cost_basis      NUMERIC(24,8),
    cost_basis_base NUMERIC(24,8),
    last_valued_at  TIMESTAMPTZ,
    UNIQUE (portfolio_id, security_id)
);

CREATE TABLE market_price (
    price_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id      UUID NOT NULL REFERENCES security,
    price_timestamp  TIMESTAMPTZ NOT NULL,
    price_type       VARCHAR(32) NOT NULL CHECK (price_type IN ('REALTIME', 'DELAYED', 'EOD')),
    open_price       NUMERIC(24,8),
    high_price       NUMERIC(24,8),
    low_price        NUMERIC(24,8),
    close_price      NUMERIC(24,8) NOT NULL,
    volume           NUMERIC(24,8),
    source           VARCHAR(64) NOT NULL,
    data_quality     VARCHAR(32) NOT NULL DEFAULT 'OK',
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (security_id, price_timestamp, price_type, source)
);

CREATE TABLE fx_rate (
    fx_rate_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_currency   CHAR(3) NOT NULL,
    to_currency     CHAR(3) NOT NULL,
    rate            NUMERIC(24,8) NOT NULL CHECK (rate > 0),
    rate_timestamp  TIMESTAMPTZ NOT NULL,
    source          VARCHAR(64) NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (from_currency, to_currency, rate_timestamp, source)
);

CREATE TABLE audit_event (
    audit_event_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID REFERENCES app_user,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    action          VARCHAR(64) NOT NULL,
    entity_type     VARCHAR(64) NOT NULL,
    entity_id       UUID,
    detail          JSONB NOT NULL DEFAULT '{}'
);

COMMIT;

// Mirrors the FastAPI response models. Money and quantities are decimal strings.

export type Dec = string;
export type CostMethod = "FIFO" | "AVERAGE";
export type TxType = "BUY" | "SELL" | "DEPOSIT" | "WITHDRAWAL" | "DIVIDEND" | "FEE";
export type PriceType = "REALTIME" | "DELAYED" | "EOD";

export interface Portfolio {
  id: string;
  name: string;
  base_currency: string;
  cost_method: CostMethod;
  objective: string | null;
  created_at: string;
  archived_at: string | null;
}

export interface Transaction {
  id: string;
  portfolio_id: string;
  type: TxType;
  trade_date: string;
  currency: string;
  symbol: string | null;
  exchange: string | null;
  quantity: Dec | null;
  unit_price: Dec | null;
  amount: Dec | null;
  brokerage_fee: Dec;
  other_fees: Dec;
  fx_rate_to_base: Dec | null;
  settlement_date: string | null;
  external_reference: string | null;
  reversed: boolean;
  reversed_reason: string | null;
}

export interface Lot {
  lot_id: string;
  acquired: string;
  quantity: Dec;
  cost_local: Dec;
  cost_base: Dec;
}

export interface Position {
  symbol: string;
  exchange: string;
  currency: string;
  quantity: Dec;
  average_cost: Dec | null;
  cost_local: Dec;
  cost_base: Dec;
  lots: Lot[];
}

export interface Holdings {
  portfolio_id: string;
  base_currency: string;
  cost_method: CostMethod;
  positions: Position[];
  cash: Record<string, Dec>;
  realised_gain_base: Dec;
  dividend_income_base: Dec;
  net_contributions_base: Dec;
  warnings: string[];
}

export interface Quote {
  price: Dec;
  currency: string;
  as_of: string;
  price_type: PriceType;
  source: string;
}

export interface FxRate {
  from_currency: string;
  to_currency: string;
  rate: Dec;
  as_of: string;
  source: string;
}

export interface HoldingValue {
  symbol: string;
  exchange: string;
  currency: string;
  quantity: Dec;
  cost_local: Dec;
  cost_base: Dec;
  quote: Quote | null;
  fx: FxRate | null;
  market_value_local: Dec | null;
  market_value_base: Dec | null;
  unrealised_base: Dec | null;
  price_effect_base: Dec | null;
  fx_effect_base: Dec | null;
  weight: Dec | null;
  stale: boolean;
  issue: string | null;
}

export interface Valuation {
  portfolio_id: string;
  base_currency: string;
  as_of: string;
  complete: boolean;
  total_value_base: Dec;
  holdings_value_base: Dec;
  cash_value_base: Dec;
  invested_capital_base: Dec;
  unrealised_base: Dec;
  realised_base: Dec;
  cash_local: Record<string, Dec>;
  currency_exposure_base: Record<string, Dec>;
  holdings: HoldingValue[];
  issues: string[];
}

export interface RefreshResult {
  updated: Record<string, Quote>;
  missing: Record<string, string>;
  fx_updated: Record<string, FxRate>;
  fx_missing: Record<string, string>;
}

export interface RowIssue {
  line: number;
  reason: string;
  raw: Record<string, string>;
}

export interface ImportResult {
  committed: number;
  mapping: Record<string, string | null>;
  valid: Transaction[];
  duplicates: RowIssue[];
  errors: RowIssue[];
}

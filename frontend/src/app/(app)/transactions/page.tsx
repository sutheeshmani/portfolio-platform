"use client";

import Link from "next/link";
import { useState } from "react";

import { Field, Loading, NeedsPortfolio, Notice, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { ApiError, api, useApi } from "@/lib/api";
import { dateTime, money, quantity } from "@/lib/format";
import { usePortfolios } from "@/lib/portfolio-context";
import type { Portfolio, Transaction, TxType } from "@/lib/types";

const TYPE_LABEL: Record<TxType, string> = {
  BUY: "Buy",
  SELL: "Sell",
  DEPOSIT: "Deposit",
  WITHDRAWAL: "Withdrawal",
  DIVIDEND: "Dividend",
  FEE: "Fee",
};

const EXCHANGES = [
  { code: "ASX", currency: "AUD" },
  { code: "NASDAQ", currency: "USD" },
  { code: "NYSE", currency: "USD" },
];

const DECIMAL = /^\d+(\.\d{1,8})?$/;

function nowLocal(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function AddTransaction({ portfolio, onSaved }: { portfolio: Portfolio; onSaved: () => void }) {
  const [type, setType] = useState<TxType>("BUY");
  const [when, setWhen] = useState(nowLocal);
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("ASX");
  const [currency, setCurrency] = useState("AUD");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [fee, setFee] = useState("");
  const [fx, setFx] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [saving, setSaving] = useState(false);

  const trade = type === "BUY" || type === "SELL";
  const withSecurity = trade || type === "DIVIDEND";
  const foreign = currency !== portfolio.base_currency;

  function pickExchange(code: string) {
    setExchange(code);
    setCurrency(EXCHANGES.find((e) => e.code === code)?.currency ?? "AUD");
  }

  function problem(): string | null {
    if (!when) return "Enter the trade date.";
    if (trade) {
      if (!symbol.trim()) return "Enter the share code, for example BHP.";
      if (!DECIMAL.test(qty) || Number(qty) <= 0) return "Quantity must be a positive number with up to 8 decimal places.";
      if (!DECIMAL.test(price) || Number(price) <= 0) return "Price must be a positive number with up to 8 decimal places.";
    } else if (!DECIMAL.test(amount) || Number(amount) <= 0) {
      return "Amount must be a positive number with up to 8 decimal places.";
    }
    if (fee && !DECIMAL.test(fee)) return "Brokerage must be a number.";
    if (foreign && (!DECIMAL.test(fx) || Number(fx) <= 0))
      return `Enter the ${currency} to ${portfolio.base_currency} exchange rate on the trade date.`;
    return null;
  }

  async function submit(e: React.FormEvent, allowDuplicate = false) {
    e.preventDefault();
    const issue = problem();
    if (issue) {
      setError(issue);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api<Transaction>("transactions", {
        method: "POST",
        body: {
          portfolio_id: portfolio.id,
          type,
          trade_date: new Date(when).toISOString(),
          currency,
          symbol: withSecurity && symbol.trim() ? symbol.trim().toUpperCase() : null,
          exchange: withSecurity && symbol.trim() ? exchange : null,
          quantity: trade ? qty : null,
          unit_price: trade ? price : null,
          amount: trade ? null : amount,
          brokerage_fee: trade && fee ? fee : "0",
          fx_rate_to_base: foreign ? fx : null,
          external_reference: reference.trim() || null,
          allow_duplicate: allowDuplicate,
        },
      });
      setSymbol("");
      setQty("");
      setPrice("");
      setAmount("");
      setFee("");
      setReference("");
      setDuplicate(false);
      onSaved();
    } catch (err) {
      setDuplicate(err instanceof ApiError && err.status === 409);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(e) => submit(e)} className="rounded border border-line bg-surface p-5" noValidate>
      <h2 className="text-lg font-semibold">Record a transaction</h2>
      {error && (
        <div className="mt-3">
          <Notice tone="error">
            {error}
            {duplicate && (
              <button
                type="button"
                className="ml-2 font-semibold text-accent underline"
                onClick={(e) => submit(e, true)}
              >
                Record it anyway
              </button>
            )}
          </Notice>
        </div>
      )}
      <div className="mt-4 grid gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Type">
            <select className={inputClass} value={type} onChange={(e) => setType(e.target.value as TxType)}>
              {Object.entries(TYPE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Date and time">
            <input type="datetime-local" className={inputClass} value={when} onChange={(e) => setWhen(e.target.value)} />
          </Field>
        </div>

        {withSecurity && (
          <div className="grid grid-cols-2 gap-4">
            <Field label={trade ? "Share code" : "Share code (optional)"}>
              <input
                className={`${inputClass} uppercase`}
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                maxLength={32}
                placeholder="BHP"
                autoCapitalize="characters"
              />
            </Field>
            <Field label="Exchange">
              <select className={inputClass} value={exchange} onChange={(e) => pickExchange(e.target.value)}>
                {EXCHANGES.map((x) => (
                  <option key={x.code} value={x.code}>
                    {x.code}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}

        {trade ? (
          <div className="grid grid-cols-3 gap-4">
            <Field label="Quantity">
              <input className={`${inputClass} num`} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="100" />
            </Field>
            <Field label={`Price (${currency})`}>
              <input className={`${inputClass} num`} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="45.20" />
            </Field>
            <Field label="Brokerage">
              <input className={`${inputClass} num`} inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} placeholder="0" />
            </Field>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Amount">
              <input className={`${inputClass} num`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            {!withSecurity && (
              <Field label="Currency">
                <select className={inputClass} value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  <option value="AUD">AUD</option>
                  <option value="USD">USD</option>
                </select>
              </Field>
            )}
          </div>
        )}

        {foreign && (
          <Field
            label={`${currency} to ${portfolio.base_currency} rate on the trade date`}
            hint={`How many ${portfolio.base_currency} one ${currency} bought. Kept with this transaction permanently.`}
          >
            <input className={`${inputClass} num`} inputMode="decimal" value={fx} onChange={(e) => setFx(e.target.value)} placeholder="1.4763" />
          </Field>
        )}

        <Field label="Broker reference (optional)" hint="Helps spot the same trade entered twice.">
          <input className={inputClass} value={reference} onChange={(e) => setReference(e.target.value)} maxLength={128} />
        </Field>
      </div>
      <button type="submit" className={`${buttonClass("primary")} mt-5`} disabled={saving}>
        {saving ? "Recording…" : `Record ${TYPE_LABEL[type].toLowerCase()}`}
      </button>
    </form>
  );
}

function ReverseButton({ tx, portfolioId, onDone }: { tx: Transaction; portfolioId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function reverse() {
    setError(null);
    try {
      await api<void>(`transactions/${tx.id}/reverse`, {
        method: "POST",
        body: { portfolio_id: portfolioId, reason: reason.trim() },
      });
      setOpen(false);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!open) {
    return (
      <button type="button" className="text-sm font-medium text-accent underline" onClick={() => setOpen(true)}>
        Reverse
      </button>
    );
  }
  return (
    <div className="mt-2 flex flex-col gap-2 text-left">
      <label className="text-sm">
        Why are you reversing it?
        <input
          className={`${inputClass} mt-1`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Entered twice"
          autoFocus
        />
      </label>
      {error && <p className="text-sm text-loss">{error}</p>}
      <div className="flex gap-2">
        <button type="button" className={buttonClass("danger")} disabled={!reason.trim()} onClick={reverse}>
          Reverse transaction
        </button>
        <button type="button" className={buttonClass()} onClick={() => setOpen(false)}>
          Keep
        </button>
      </div>
    </div>
  );
}

export default function TransactionsPage() {
  const { selected, portfolios, loading: portfoliosLoading } = usePortfolios();
  const [showReversed, setShowReversed] = useState(true);
  const { data, error, loading, reload } = useApi<Transaction[]>(
    selected
      ? `transactions?portfolio_id=${selected.id}${showReversed ? "" : "&include_reversed=false"}`
      : null,
  );

  if (portfoliosLoading && portfolios.length === 0) return <Loading what="your portfolios" />;
  if (!selected) return <NeedsPortfolio />;
  const rows = data ? [...data].reverse() : [];

  return (
    <>
      <PageHeader
        title="Transactions"
        description="Every buy, sell and cash movement. Entries are never edited; a mistake is reversed with a reason and entered again."
        actions={
          <Link href="/transactions/import" className={buttonClass()}>
            Import a CSV
          </Link>
        }
      />
      <div className="grid gap-8 xl:grid-cols-[1fr_26rem]">
        <section aria-labelledby="history" className="min-w-0">
          <div className="flex items-center justify-between">
            <h2 id="history" className="text-lg font-semibold">
              History
            </h2>
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" checked={showReversed} onChange={(e) => setShowReversed(e.target.checked)} />
              Show reversed
            </label>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          {loading && !data && <Loading what="transactions" />}
          {data && rows.length === 0 && (
            <p className="mt-4 text-ink-soft">No transactions yet. Record one, or import your broker&apos;s CSV.</p>
          )}
          {rows.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[40rem] text-left text-[15px]">
                <thead className="border-b border-line text-sm text-ink-soft">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Date</th>
                    <th className="py-2 pr-4 font-medium">Type</th>
                    <th className="py-2 pr-4 font-medium">Share</th>
                    <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                    <th className="py-2 pr-4 text-right font-medium">Price or amount</th>
                    <th className="py-2 pr-4 text-right font-medium">Fees</th>
                    <th className="py-2 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.id} className={`border-b border-line/70 align-top ${t.reversed ? "text-ink-soft" : ""}`}>
                      <td className="py-2.5 pr-4 whitespace-nowrap">{dateTime(t.trade_date)}</td>
                      <td className="py-2.5 pr-4">{TYPE_LABEL[t.type]}</td>
                      <td className="py-2.5 pr-4">
                        {t.symbol ? (
                          <>
                            <span className="font-medium">{t.symbol}</span>
                            <span className="ml-1 text-sm text-ink-soft">{t.exchange}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="num py-2.5 pr-4 text-right">{t.quantity ? quantity(t.quantity) : ""}</td>
                      <td className="num py-2.5 pr-4 text-right">
                        {money(t.unit_price ?? t.amount, t.currency, t.unit_price ? 4 : 2)}
                      </td>
                      <td className="num py-2.5 pr-4 text-right">
                        {t.brokerage_fee !== "0" && Number(t.brokerage_fee) !== 0 ? money(t.brokerage_fee, t.currency) : ""}
                      </td>
                      <td className="py-2.5 text-right">
                        {t.reversed ? (
                          <span className="text-sm">Reversed: {t.reversed_reason}</span>
                        ) : (
                          <ReverseButton tx={t} portfolioId={selected.id} onDone={reload} />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <AddTransaction portfolio={selected} onSaved={reload} />
      </div>
    </>
  );
}

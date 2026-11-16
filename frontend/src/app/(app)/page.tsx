"use client";

import { useState } from "react";

import {
  Freshness,
  Loading,
  NeedsPortfolio,
  Notice,
  PageHeader,
  Signed,
  buttonClass,
} from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { age, dateTime, money, percent, quantity } from "@/lib/format";
import { usePortfolios } from "@/lib/portfolio-context";
import type { RefreshResult, Valuation } from "@/lib/types";

/** Turn the API's issue codes into sentences. */
function describeIssue(issue: string): string {
  const [code, ...rest] = issue.split(" ");
  const subject = rest.join(" ");
  if (code === "MISSING_PRICE") return `No price yet for ${subject}, so it's left out of the total.`;
  if (code === "MISSING_FX")
    return `No exchange rate yet for ${subject.replace("->", " to ")}. Holdings and cash in that currency are left out of the total.`;
  if (code === "STALE") {
    const m = /^(\S+) price as of (.+)$/.exec(subject);
    if (m) return `The price for ${m[1]} is from ${dateTime(m[2])}.`;
    return `The ${subject.replace("->", " to ")} rate is old.`;
  }
  return issue;
}

function sourcesLine(v: Valuation): string | null {
  const quotes = v.holdings.flatMap((h) => (h.quote ? [h.quote] : []));
  if (quotes.length === 0) return null;
  const sources = [...new Set(quotes.map((q) => q.source))].join(" and ");
  const delayed = quotes.some((q) => q.price_type === "DELAYED");
  const oldest = quotes.reduce((a, b) => (a.as_of < b.as_of ? a : b));
  return `Prices from ${sources}${delayed ? ", delayed 15–20 minutes" : ""}. Oldest price ${age(oldest.as_of)} (${dateTime(oldest.as_of)}).`;
}

function ExposureBar({ v }: { v: Valuation }) {
  const entries = Object.entries(v.currency_exposure_base);
  const total = entries.reduce((sum, [, value]) => sum + Math.max(0, Number(value)), 0);
  if (entries.length === 0 || total <= 0) return null;
  const tones = ["bg-accent", "bg-ink-soft", "bg-stale"];
  return (
    <section aria-labelledby="exposure" className="mt-10">
      <h2 id="exposure" className="text-lg font-semibold">
        Currency exposure
      </h2>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-line" aria-hidden="true">
        {entries.map(([ccy, value], i) => (
          <div
            key={ccy}
            className={tones[i % tones.length]}
            style={{ width: `${(Math.max(0, Number(value)) / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[15px]">
        {entries.map(([ccy, value], i) => (
          <li key={ccy} className="flex items-center gap-2">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${tones[i % tones.length]}`} />
            <span className="font-medium">{ccy}</span>
            <span className="num text-ink-soft">
              {money(value, v.base_currency)} ({((Math.max(0, Number(value)) / total) * 100).toFixed(1)}%)
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function DashboardPage() {
  const { selected, portfolios, loading: portfoliosLoading } = usePortfolios();
  const path = selected ? `portfolios/${selected.id}/valuation` : null;
  const { data: v, error, loading, reload } = useApi<Valuation>(path);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<{ tone: "success" | "warning" | "error"; text: string } | null>(null);

  async function refresh() {
    if (!selected) return;
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api<RefreshResult>(`portfolios/${selected.id}/prices/refresh`, {
        method: "POST",
      });
      const updated = Object.keys(r.updated).length;
      const missing = [...Object.keys(r.missing), ...Object.keys(r.fx_missing)];
      setRefreshNote({
        tone: missing.length ? "warning" : "success",
        text:
          `Updated ${updated} price${updated === 1 ? "" : "s"}` +
          (Object.keys(r.fx_updated).length ? " and the exchange rate" : "") +
          "." +
          (missing.length ? ` Nothing came back for ${missing.join(", ")}.` : ""),
      });
      reload();
    } catch (err) {
      setRefreshNote({ tone: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setRefreshing(false);
    }
  }

  if (portfoliosLoading && portfolios.length === 0) return <Loading what="your portfolios" />;
  if (!selected) return <NeedsPortfolio />;

  const ccy = selected.base_currency;
  const provenance = v ? sourcesLine(v) : null;

  return (
    <>
      <PageHeader
        title={selected.name}
        description={selected.objective ?? undefined}
        actions={
          <button type="button" className={buttonClass("secondary")} onClick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing prices…" : "Refresh prices"}
          </button>
        }
      />

      {refreshNote && <Notice tone={refreshNote.tone}>{refreshNote.text}</Notice>}
      {error && <Notice tone="error" title="Couldn't load the valuation">{error}</Notice>}
      {loading && !v && <Loading what="the valuation" />}

      {v && (
        <>
          <section aria-labelledby="total">
            <h2 id="total" className="text-[15px] font-medium text-ink-soft">
              Total value in {ccy}
            </h2>
            <p className="num mt-1 text-5xl font-bold tracking-tight md:text-6xl">
              {money(v.total_value_base, ccy)}
            </p>
            <p className="mt-3 max-w-2xl text-[15px] text-ink-soft">
              {provenance ??
                (v.holdings.length
                  ? "No prices stored yet. Refresh prices to value your holdings."
                  : "Cash only. Holdings appear here once you record a purchase.")}
            </p>
          </section>

          {v.issues.length > 0 && (
            <div className="mt-6">
              <Notice
                tone="warning"
                title={v.complete ? "Some prices are old" : "This total is incomplete"}
              >
                <ul className="list-disc space-y-0.5 pl-5">
                  {v.issues.map((i) => (
                    <li key={i}>{describeIssue(i)}</li>
                  ))}
                </ul>
              </Notice>
            </div>
          )}

          <dl className="mt-8 grid grid-cols-2 gap-y-5 border-y border-line py-5 md:grid-cols-5">
            {[
              ["Holdings", <span key="h" className="num">{money(v.holdings_value_base, ccy)}</span>],
              ["Cash", <span key="c" className="num">{money(v.cash_value_base, ccy)}</span>],
              ["Invested capital", <span key="i" className="num">{money(v.invested_capital_base, ccy)}</span>],
              ["Unrealised gain", <Signed key="u" value={v.unrealised_base} currency={ccy} />],
              ["Realised gain", <Signed key="r" value={v.realised_base} currency={ccy} />],
            ].map(([label, value], i) => (
              <div key={i} className="md:border-l md:border-line md:pl-5 md:first:border-l-0 md:first:pl-0">
                <dt className="text-sm text-ink-soft">{label}</dt>
                <dd className="mt-0.5 text-lg font-semibold">{value}</dd>
              </div>
            ))}
          </dl>

          <ExposureBar v={v} />

          <section aria-labelledby="holdings" className="mt-10">
            <h2 id="holdings" className="text-lg font-semibold">
              Holdings
            </h2>
            {v.holdings.length === 0 ? (
              <p className="mt-2 text-ink-soft">No shares held in this portfolio.</p>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[46rem] text-left text-[15px]">
                  <thead className="border-b border-line text-sm text-ink-soft">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Share</th>
                      <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                      <th className="py-2 pr-4 text-right font-medium">Price</th>
                      <th className="py-2 pr-4 text-right font-medium">Value ({ccy})</th>
                      <th className="py-2 pr-4 text-right font-medium">Unrealised</th>
                      <th className="py-2 text-right font-medium">Weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.holdings.map((h) => (
                      <tr key={`${h.symbol}:${h.exchange}`} className="border-b border-line/70 align-top">
                        <td className="py-3 pr-4">
                          <span className="font-semibold">{h.symbol}</span>
                          <span className="ml-1.5 text-sm text-ink-soft">{h.exchange}</span>
                        </td>
                        <td className="num py-3 pr-4 text-right">{quantity(h.quantity)}</td>
                        <td className="py-3 pr-4 text-right">
                          <span className="num block">{h.quote ? money(h.quote.price, h.currency) : "—"}</span>
                          <Freshness quote={h.quote} stale={h.stale} />
                        </td>
                        <td className="num py-3 pr-4 text-right font-medium">{money(h.market_value_base, ccy)}</td>
                        <td className="py-3 pr-4 text-right">
                          <Signed value={h.unrealised_base} currency={ccy} />
                          {h.currency !== ccy && h.fx_effect_base && (
                            <span className="block text-[13px] text-ink-soft">
                              Price <span className="num">{money(h.price_effect_base, ccy)}</span>, currency{" "}
                              <span className="num">{money(h.fx_effect_base, ccy)}</span>
                            </span>
                          )}
                        </td>
                        <td className="py-3 text-right">
                          <span className="num">{percent(h.weight)}</span>
                          <span className="ml-auto mt-1.5 block h-1 w-20 rounded-full bg-line" aria-hidden="true">
                            <span
                              className="block h-1 rounded-full bg-accent"
                              style={{ width: `${Math.min(100, Number(h.weight ?? 0) * 100)}%` }}
                            />
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <p className="mt-8 text-[13px] text-ink-soft">
            Valued {dateTime(v.as_of)} Sydney time. Cost includes brokerage and uses the exchange
            rate on each trade date; current values use the latest stored rate.
          </p>
        </>
      )}
    </>
  );
}

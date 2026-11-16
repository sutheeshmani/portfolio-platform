"use client";

import { Loading, NeedsPortfolio, Notice, PageHeader, Signed } from "@/components/ui";
import { useApi } from "@/lib/api";
import { date, money, quantity } from "@/lib/format";
import { usePortfolios } from "@/lib/portfolio-context";
import type { Holdings } from "@/lib/types";

export default function HoldingsPage() {
  const { selected, portfolios, loading: portfoliosLoading } = usePortfolios();
  const { data: h, error, loading } = useApi<Holdings>(
    selected ? `portfolios/${selected.id}/holdings` : null,
  );

  if (portfoliosLoading && portfolios.length === 0) return <Loading what="your portfolios" />;
  if (!selected) return <NeedsPortfolio />;
  const ccy = selected.base_currency;

  return (
    <>
      <PageHeader
        title="Holdings"
        description={`What ${selected.name} holds, worked out from its transactions. Each purchase is kept as a separate parcel.`}
      />
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !h && <Loading what="holdings" />}
      {h && (
        <>
          {h.warnings.length > 0 && (
            <Notice tone="warning" title="Check your cash records">
              <ul className="list-disc pl-5">
                {h.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}

          {h.positions.length === 0 ? (
            <p className="text-ink-soft">No shares held. Record a purchase to see it here.</p>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {h.positions.map((p) => (
                <li key={`${p.symbol}:${p.exchange}`}>
                  <details className="group">
                    <summary className="grid cursor-pointer grid-cols-2 gap-2 py-4 md:grid-cols-5 md:items-center">
                      <span>
                        <span className="font-semibold">{p.symbol}</span>
                        <span className="ml-1.5 text-sm text-ink-soft">{p.exchange}</span>
                        <span className="block text-sm text-ink-soft">
                          {p.lots.length} parcel{p.lots.length === 1 ? "" : "s"}
                        </span>
                      </span>
                      <span className="num text-right md:text-left">
                        {quantity(p.quantity)} <span className="text-sm text-ink-soft">shares</span>
                      </span>
                      <span className="text-sm text-ink-soft md:text-base md:text-ink">
                        <span className="md:hidden">Average </span>
                        <span className="num">{money(p.average_cost, p.currency, 4)}</span>
                      </span>
                      <span className="num text-right md:text-left">{money(p.cost_local, p.currency)}</span>
                      <span className="num text-right">
                        {p.currency !== ccy ? money(p.cost_base, ccy) : ""}
                      </span>
                    </summary>
                    <table className="mb-4 w-full text-left text-[15px]">
                      <caption className="sr-only">Parcels of {p.symbol}</caption>
                      <thead className="text-sm text-ink-soft">
                        <tr>
                          <th className="py-1 pr-4 font-medium">Bought</th>
                          <th className="py-1 pr-4 text-right font-medium">Remaining</th>
                          <th className="py-1 pr-4 text-right font-medium">Cost ({p.currency})</th>
                          <th className="py-1 text-right font-medium">Cost ({ccy})</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.lots.map((lot) => (
                          <tr key={lot.lot_id} className="border-t border-line/70">
                            <td className="py-1.5 pr-4">{date(lot.acquired)}</td>
                            <td className="num py-1.5 pr-4 text-right">{quantity(lot.quantity)}</td>
                            <td className="num py-1.5 pr-4 text-right">{money(lot.cost_local, p.currency)}</td>
                            <td className="num py-1.5 text-right">{money(lot.cost_base, ccy)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[13px] text-ink-soft">
            Columns: share, quantity, average cost, total cost, and total cost in {ccy} for foreign
            shares at trade-date exchange rates. Open a row to see its parcels.
          </p>

          <div className="mt-10 grid gap-8 md:grid-cols-2">
            <section aria-labelledby="cash">
              <h2 id="cash" className="text-lg font-semibold">
                Cash
              </h2>
              {Object.keys(h.cash).length === 0 ? (
                <p className="mt-2 text-ink-soft">No cash recorded.</p>
              ) : (
                <dl className="mt-2 divide-y divide-line border-y border-line">
                  {Object.entries(h.cash).map(([c, amount]) => (
                    <div key={c} className="flex justify-between py-2.5">
                      <dt>{c}</dt>
                      <dd className="num font-medium">{money(amount, c)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
            <section aria-labelledby="totals">
              <h2 id="totals" className="text-lg font-semibold">
                Totals in {ccy}
              </h2>
              <dl className="mt-2 divide-y divide-line border-y border-line">
                <div className="flex justify-between py-2.5">
                  <dt>Money put in, less withdrawals</dt>
                  <dd className="num font-medium">{money(h.net_contributions_base, ccy)}</dd>
                </div>
                <div className="flex justify-between py-2.5">
                  <dt>Realised gain on sales</dt>
                  <dd className="font-medium">
                    <Signed value={h.realised_gain_base} currency={ccy} />
                  </dd>
                </div>
                <div className="flex justify-between py-2.5">
                  <dt>Dividends received</dt>
                  <dd className="num font-medium">{money(h.dividend_income_base, ccy)}</dd>
                </div>
              </dl>
            </section>
          </div>
        </>
      )}
    </>
  );
}

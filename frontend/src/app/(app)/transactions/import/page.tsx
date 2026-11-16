"use client";

import Link from "next/link";
import { useState } from "react";

import { Field, NeedsPortfolio, Notice, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { date, money, quantity } from "@/lib/format";
import { usePortfolios } from "@/lib/portfolio-context";
import type { ImportResult, RowIssue } from "@/lib/types";

const MAX_BYTES = 2_000_000;

function Issues({ title, rows }: { title: string; rows: RowIssue[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">
        {title} ({rows.length})
      </h2>
      <ul className="mt-2 divide-y divide-line border-y border-line text-[15px]">
        {rows.map((r) => (
          <li key={r.line} className="py-2">
            <span className="num font-medium">Line {r.line}:</span> {r.reason}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function ImportPage() {
  const { selected } = usePortfolios();
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!selected) return <NeedsPortfolio />;
  const portfolioId = selected.id;

  async function readFile(file: File | undefined) {
    setPreview(null);
    setDone(null);
    setError(null);
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("That file is over 2 MB. Split it into smaller files.");
      return;
    }
    setFileName(file.name);
    setText(await file.text());
  }

  async function run(commit: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await api<ImportResult>("transactions/import", {
        method: "POST",
        body: { portfolio_id: portfolioId, csv_text: text, commit, file_name: fileName },
      });
      if (commit) {
        setDone(result.committed);
        setPreview(null);
        setText("");
        setFileName(null);
      } else {
        setPreview(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Import transactions"
        description={`Add trades from your broker's CSV export to ${selected.name}. Nothing is saved until you confirm the preview.`}
        actions={
          <Link href="/transactions" className={buttonClass()}>
            Back to transactions
          </Link>
        }
      />

      {done !== null && (
        <Notice tone="success" title={`Imported ${done} transaction${done === 1 ? "" : "s"}`}>
          They&apos;re in your transaction history and holdings now.
        </Notice>
      )}
      {error && <Notice tone="error" title="The import didn't go through">{error}</Notice>}

      <div className="grid gap-5 rounded border border-line bg-surface p-5">
        <Field label="CSV file" hint="Columns are matched by name: date, buy or sell, code, units, price, brokerage. Dates are read as day/month/year, Sydney time.">
          <input
            type="file"
            accept=".csv,text/csv"
            className="block text-sm"
            onChange={(e) => readFile(e.target.files?.[0])}
          />
        </Field>
        <Field label="Or paste the CSV">
          <textarea
            className={`${inputClass} num h-40 font-normal`}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPreview(null);
              setFileName(null);
            }}
            placeholder={"Trade Date,Side,Symbol,Units,Price,Brokerage\n03/02/2026,Buy,BHP,100,45.20,3.00"}
            spellCheck={false}
          />
        </Field>
        <div>
          <button type="button" className={buttonClass("primary")} disabled={!text.trim() || busy} onClick={() => run(false)}>
            {busy && !preview ? "Checking…" : "Preview import"}
          </button>
        </div>
      </div>

      {preview && (
        <>
          <section className="mt-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Ready to import ({preview.valid.length})</h2>
              <button
                type="button"
                className={buttonClass("primary")}
                disabled={preview.valid.length === 0 || busy}
                onClick={() => run(true)}
              >
                {busy ? "Importing…" : `Import ${preview.valid.length} transaction${preview.valid.length === 1 ? "" : "s"}`}
              </button>
            </div>
            <p className="mt-1 text-[15px] text-ink-soft">
              Columns used:{" "}
              {Object.entries(preview.mapping)
                .filter(([key, v]) => typeof v === "string" && ["date", "type", "symbol", "quantity", "price", "fees", "reference"].includes(key))
                .map(([key, v]) => `${key} from “${v}”`)
                .join(", ")}
              .
            </p>
            {preview.valid.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[36rem] text-left text-[15px]">
                  <thead className="border-b border-line text-sm text-ink-soft">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Date</th>
                      <th className="py-2 pr-4 font-medium">Type</th>
                      <th className="py-2 pr-4 font-medium">Share</th>
                      <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                      <th className="py-2 pr-4 text-right font-medium">Price</th>
                      <th className="py-2 text-right font-medium">Brokerage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.valid.map((t) => (
                      <tr key={t.id} className="border-b border-line/70">
                        <td className="py-2 pr-4">{date(t.trade_date)}</td>
                        <td className="py-2 pr-4">{t.type === "BUY" ? "Buy" : "Sell"}</td>
                        <td className="py-2 pr-4 font-medium">
                          {t.symbol} <span className="text-sm font-normal text-ink-soft">{t.exchange}</span>
                        </td>
                        <td className="num py-2 pr-4 text-right">{quantity(t.quantity)}</td>
                        <td className="num py-2 pr-4 text-right">{money(t.unit_price, t.currency, 4)}</td>
                        <td className="num py-2 text-right">{money(t.brokerage_fee, t.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <Issues title="Already in your history, will be skipped" rows={preview.duplicates} />
          <Issues title="Rows with problems, will be skipped" rows={preview.errors} />
        </>
      )}
    </>
  );
}

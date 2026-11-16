"use client";

import { useState } from "react";

import { Field, Loading, Notice, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { date } from "@/lib/format";
import { usePortfolios } from "@/lib/portfolio-context";
import type { CostMethod, Portfolio } from "@/lib/types";

function CreateForm({ onCreated }: { onCreated: (p: Portfolio) => void }) {
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [costMethod, setCostMethod] = useState<CostMethod>("FIFO");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await api<Portfolio>("portfolios", {
        method: "POST",
        body: {
          name: name.trim(),
          base_currency: "AUD",
          cost_method: costMethod,
          objective: objective.trim() || null,
        },
      });
      setName("");
      setObjective("");
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded border border-line bg-surface p-5">
      <h2 className="text-lg font-semibold">New portfolio</h2>
      {error && (
        <div className="mt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Name">
          <input
            className={inputClass}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={128}
            placeholder="Long-term growth"
          />
        </Field>
        <Field
          label="How sales are matched to purchases"
          hint="First in, first out sells your oldest shares first. Neither is a tax calculation."
        >
          <select
            className={inputClass}
            value={costMethod}
            onChange={(e) => setCostMethod(e.target.value as CostMethod)}
          >
            <option value="FIFO">First in, first out</option>
            <option value="AVERAGE">Average cost</option>
          </select>
        </Field>
        <div className="md:col-span-2">
          <Field label="Objective (optional)">
            <input
              className={inputClass}
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              maxLength={2000}
              placeholder="Dividend income from ASX blue chips"
            />
          </Field>
        </div>
      </div>
      <p className="mt-4 text-[13px] text-ink-soft">Values are reported in AUD.</p>
      <button type="submit" className={`${buttonClass("primary")} mt-4`} disabled={saving || !name.trim()}>
        {saving ? "Creating…" : "Create portfolio"}
      </button>
    </form>
  );
}

export default function PortfoliosPage() {
  const { reload: reloadSwitcher, select, selected } = usePortfolios();
  const [showArchived, setShowArchived] = useState(false);
  const { data, error, loading, reload } = useApi<Portfolio[]>(
    `portfolios${showArchived ? "?include_archived=true" : ""}`,
  );
  const [confirming, setConfirming] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function archive(id: string) {
    setActionError(null);
    try {
      await api<Portfolio>(`portfolios/${id}`, { method: "DELETE" });
      setConfirming(null);
      reload();
      reloadSwitcher();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <PageHeader
        title="My portfolios"
        description="Keep separate portfolios for different strategies or brokerage accounts."
      />
      <div className="grid gap-8 lg:grid-cols-[1fr_24rem]">
        <section aria-labelledby="list">
          <div className="flex items-center justify-between">
            <h2 id="list" className="text-lg font-semibold">
              Portfolios
            </h2>
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
              />
              Show archived
            </label>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          {actionError && <Notice tone="error">{actionError}</Notice>}
          {loading && !data && <Loading what="portfolios" />}
          {data && data.length === 0 && (
            <p className="mt-4 text-ink-soft">No portfolios yet. Create your first one.</p>
          )}
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {data?.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <p className="font-semibold">
                    {p.name}
                    {selected?.id === p.id && (
                      <span className="ml-2 text-sm font-normal text-accent">Showing</span>
                    )}
                    {p.archived_at && (
                      <span className="ml-2 text-sm font-normal text-ink-soft">Archived</span>
                    )}
                  </p>
                  <p className="text-sm text-ink-soft">
                    {p.cost_method === "FIFO" ? "First in, first out" : "Average cost"}, {p.base_currency}, created{" "}
                    {date(p.created_at)}
                  </p>
                  {p.objective && <p className="mt-1 text-[15px]">{p.objective}</p>}
                </div>
                {!p.archived_at && (
                  <div className="flex gap-2">
                    {selected?.id !== p.id && (
                      <button type="button" className={buttonClass()} onClick={() => select(p.id)}>
                        Show
                      </button>
                    )}
                    {confirming === p.id ? (
                      <>
                        <button type="button" className={buttonClass("danger")} onClick={() => archive(p.id)}>
                          Archive {p.name}
                        </button>
                        <button type="button" className={buttonClass()} onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                      </>
                    ) : (
                      <button type="button" className={buttonClass()} onClick={() => setConfirming(p.id)}>
                        Archive
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[13px] text-ink-soft">
            Archiving hides a portfolio and stops new transactions. Nothing is deleted.
          </p>
        </section>
        <CreateForm
          onCreated={(p) => {
            reload();
            reloadSwitcher();
            select(p.id);
          }}
        />
      </div>
    </>
  );
}

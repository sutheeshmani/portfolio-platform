"use client";

import Link from "next/link";

import { age, dateTime, sign, signedMoney } from "@/lib/format";
import type { Quote } from "@/lib/types";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">{title}</h1>
        {description && <p className="mt-1.5 text-ink-soft">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const NOTICE = {
  error: "border-loss/40 bg-loss/5",
  warning: "border-stale/40 bg-stale-soft",
  info: "border-line bg-surface",
  success: "border-gain/40 bg-gain/5",
} as const;

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: keyof typeof NOTICE;
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`mb-6 rounded border px-4 py-3 text-[15px] ${NOTICE[tone]}`}
    >
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-1 text-ink-soft" : ""}>{children}</div>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="py-10 text-ink-soft">Loading {what}…</p>;
}

/** Gain or loss in colour, always with a sign so colour isn't the only signal. */
export function Signed({ value, currency = "AUD" }: { value: string | null; currency?: string }) {
  const s = sign(value);
  const tone = s > 0 ? "text-gain" : s < 0 ? "text-loss" : "text-ink";
  return <span className={`num ${tone}`}>{signedMoney(value, currency)}</span>;
}

const PRICE_TYPE = { REALTIME: "Live", DELAYED: "Delayed", EOD: "Close" } as const;

/** Where a price came from and how old it is. Stale prices are marked in amber. */
export function Freshness({ quote, stale }: { quote: Quote | null; stale?: boolean }) {
  if (!quote) return <span className="text-sm text-loss">No price</span>;
  return (
    <span
      className={`text-[13px] ${stale ? "font-medium text-stale" : "text-ink-soft"}`}
      title={`${quote.source}, ${dateTime(quote.as_of)}`}
    >
      {PRICE_TYPE[quote.price_type]}, {age(quote.as_of)}
      {stale && " (stale)"}
    </span>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: { href: string; label: string };
}) {
  return (
    <div className="rounded border border-dashed border-line px-6 py-12 text-center">
      <p className="text-lg font-semibold">{title}</p>
      {children && <p className="mx-auto mt-2 max-w-md text-ink-soft">{children}</p>}
      {action && (
        <Link href={action.href} className={`${buttonClass("primary")} mt-5 inline-block`}>
          {action.label}
        </Link>
      )}
    </div>
  );
}

export function buttonClass(kind: "primary" | "secondary" | "danger" = "secondary"): string {
  const base =
    "rounded px-3.5 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50";
  if (kind === "primary") return `${base} bg-accent text-surface hover:opacity-90`;
  if (kind === "danger") return `${base} border border-loss/50 text-loss hover:bg-loss/5`;
  return `${base} border border-line bg-surface text-ink hover:border-ink-soft`;
}

export const inputClass =
  "w-full rounded border border-line bg-surface px-3 py-2 text-ink placeholder:text-ink-soft/70";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[13px] text-ink-soft">{hint}</span>}
    </label>
  );
}

export function NeedsPortfolio() {
  return (
    <EmptyState
      title="No portfolio yet"
      action={{ href: "/portfolios", label: "Create a portfolio" }}
    >
      Create a portfolio, then record or import your trades. Holdings and values are worked out
      from those transactions.
    </EmptyState>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { PortfolioProvider, usePortfolios } from "@/lib/portfolio-context";

import { NAV, isActive } from "./nav";
import { ThemeToggle } from "./ThemeToggle";

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-6 px-3 py-5 text-[15px]">
      {NAV.map((group, i) => (
        <div key={group.label || i}>
          {group.label && (
            <p className="mb-1.5 px-3 text-[13px] font-medium text-ink-soft">{group.label}</p>
          )}
          <ul className="flex flex-col">
            {group.items.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={[
                      "flex items-center justify-between gap-2 border-l-2 px-3 py-1.5",
                      active
                        ? "border-accent font-semibold text-ink"
                        : "border-transparent text-ink-soft hover:text-ink",
                    ].join(" ")}
                  >
                    <span>{item.label}</span>
                    {!item.ready && (
                      <span className="text-xs font-normal text-ink-soft/80">Planned</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function PortfolioSwitcher() {
  const { portfolios, selected, select, loading } = usePortfolios();
  if (loading && portfolios.length === 0) {
    return <span className="text-sm text-ink-soft">Loading portfolios…</span>;
  }
  if (portfolios.length === 0) {
    return (
      <Link href="/portfolios" className="text-sm font-medium text-accent underline">
        Create a portfolio
      </Link>
    );
  }
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-ink-soft">Portfolio</span>
      <select
        value={selected?.id ?? ""}
        onChange={(e) => select(e.target.value)}
        className="rounded border border-line bg-surface px-2 py-1 font-medium text-ink"
      >
        {portfolios.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => setMenuOpen(false), [pathname]);

  return (
    <PortfolioProvider>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <div className="md:grid md:grid-cols-[15.5rem_1fr]">
        <aside className="hidden border-r border-line md:block md:min-h-screen">
          <div className="sticky top-0">
            <Link href="/" className="block px-6 pt-6 text-lg font-bold tracking-tight">
              Portfolio
            </Link>
            <p className="px-6 text-[13px] text-ink-soft">ASX and US shares, in AUD</p>
            <Sidebar />
          </div>
        </aside>

        <div className="min-w-0">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-8">
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="rounded border border-line px-2.5 py-1 text-sm md:hidden"
                aria-expanded={menuOpen}
                aria-controls="mobile-nav"
                onClick={() => setMenuOpen((open) => !open)}
              >
                {menuOpen ? "Close" : "Menu"}
              </button>
              <PortfolioSwitcher />
            </div>
            <ThemeToggle />
          </header>

          {menuOpen && (
            <div id="mobile-nav" className="border-b border-line bg-surface md:hidden">
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </div>
          )}

          <main id="main" className="mx-auto max-w-6xl px-4 py-8 md:px-8">
            {children}
          </main>
        </div>
      </div>
    </PortfolioProvider>
  );
}

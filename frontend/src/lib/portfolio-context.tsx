"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useApi } from "./api";
import type { Portfolio } from "./types";

const STORAGE_KEY = "pp.selectedPortfolio";

interface PortfolioState {
  portfolios: Portfolio[];
  selected: Portfolio | null;
  loading: boolean;
  error: string | null;
  select: (id: string) => void;
  reload: () => void;
}

const Context = createContext<PortfolioState | null>(null);

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function PortfolioProvider({ children }: { children: React.ReactNode }) {
  const { data, error, loading, reload } = useApi<Portfolio[]>("portfolios");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    setSelectedId(readStored());
  }, []);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // Storage can be unavailable (private mode); the choice then lasts for this visit.
    }
  }, []);

  const value = useMemo<PortfolioState>(() => {
    const portfolios = data ?? [];
    const selected = portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null;
    return { portfolios, selected, loading, error, select, reload };
  }, [data, selectedId, loading, error, select, reload]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePortfolios(): PortfolioState {
  const value = useContext(Context);
  if (!value) throw new Error("usePortfolios must be used inside PortfolioProvider");
  return value;
}

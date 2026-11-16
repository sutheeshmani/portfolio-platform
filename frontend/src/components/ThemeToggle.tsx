"use client";

import { useEffect, useState } from "react";

export function ThemeToggle() {
  const [dark, setDark] = useState<boolean | null>(null);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      window.localStorage.setItem("pp.theme", next ? "dark" : "light");
    } catch {
      // Without storage the theme still applies for this visit.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded border border-line px-2.5 py-1 text-sm text-ink-soft hover:text-ink"
    >
      {dark === null ? "Theme" : dark ? "Light mode" : "Dark mode"}
    </button>
  );
}

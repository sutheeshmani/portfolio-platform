"use client";

import { useState } from "react";

import { Notice, buttonClass, inputClass } from "@/components/ui";

export default function LoginPage() {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (response.ok) {
        window.location.assign("/");
        return;
      }
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? "Sign-in failed.");
    } catch {
      setError("Couldn't reach the app. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <h1 className="text-[1.75rem] font-bold tracking-tight">Portfolio</h1>
      <p className="mt-1 text-ink-soft">Your ASX and US shares, valued in AUD.</p>
      <form onSubmit={submit} className="mt-8">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="block">
          <span className="mb-1 block text-sm font-medium">API token</span>
          <input
            type="password"
            className={inputClass}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="current-password"
            required
          />
          <span className="mt-1 block text-[13px] text-ink-soft">
            The API_TOKEN value the back end was started with.
          </span>
        </label>
        <button type="submit" className={`${buttonClass("primary")} mt-5 w-full`} disabled={busy || !token}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

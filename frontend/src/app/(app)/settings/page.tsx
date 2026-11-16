"use client";

import { useState } from "react";

import { PageHeader, buttonClass } from "@/components/ui";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function SettingsPage() {
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    await fetch("/api/session", { method: "DELETE" }).catch(() => undefined);
    window.location.assign("/login");
  }

  return (
    <>
      <PageHeader title="Settings" />
      <dl className="max-w-2xl divide-y divide-line border-y border-line">
        <div className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div>
            <dt className="font-semibold">Reporting currency</dt>
            <dd className="text-ink-soft">AUD. USD holdings and cash are converted at the latest stored rate.</dd>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div>
            <dt className="font-semibold">Time zone</dt>
            <dd className="text-ink-soft">Dates and times are shown in Sydney time.</dd>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div>
            <dt className="font-semibold">Appearance</dt>
            <dd className="text-ink-soft">Switch between light and dark.</dd>
          </div>
          <ThemeToggle />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div>
            <dt className="font-semibold">Sign-in</dt>
            <dd className="text-ink-soft">
              Signed in with your API token. Multi-factor sign-in arrives with the identity
              provider.
            </dd>
          </div>
          <button type="button" className={buttonClass()} onClick={signOut} disabled={signingOut}>
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </dl>
    </>
  );
}

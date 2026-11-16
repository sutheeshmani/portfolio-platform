import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Watchlists" };

export default function Page() {
  return (
    <PlannedPage
      title="Watchlists"
      summary="Keep an eye on shares you don't own yet."
      phase="phase 2"
      features={[
        "Create several watchlists",
        "Add and remove ASX and US shares",
        "See prices and daily moves at a glance",
      ]}
    />
  );
}

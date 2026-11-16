import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Dividends" };

export default function Page() {
  return (
    <PlannedPage
      title="Dividends"
      summary="Income from your shares, including franking and withholding tax."
      phase="phase 2"
      features={[
        "Record dividends and reinvestments",
        "Track ex-dividend and payment dates",
        "Track franking credits and US withholding tax",
      ]}
    />
  );
}

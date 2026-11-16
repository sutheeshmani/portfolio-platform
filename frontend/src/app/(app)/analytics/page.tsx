import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return (
    <PlannedPage
      title="Analytics"
      summary="How your portfolio has performed over time."
      phase="phase 2"
      features={[
        "See time-weighted and money-weighted returns",
        "Compare against the ASX 200, S&P 500 and NASDAQ 100",
        "Track drawdown, volatility and CAGR",
      ]}
    />
  );
}

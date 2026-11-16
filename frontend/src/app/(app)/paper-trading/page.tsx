import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Paper trading" };

export default function Page() {
  return (
    <PlannedPage
      title="Paper trading"
      summary="Practise with virtual cash before risking real money."
      phase="phase 3"
      simulated      features={[
        "Create practice portfolios with virtual starting cash",
        "Place simulated buys and sells with realistic brokerage",
        "Compare practice results with your real portfolios",
      ]}
    />
  );
}

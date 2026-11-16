import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Risk management" };

export default function Page() {
  return (
    <PlannedPage
      title="Risk management"
      summary="Spot concentration and currency risk before it matters."
      phase="phase 2"
      features={[
        "See each position's weight against your limits",
        "Check sector, country and currency exposure",
        "Get alerts when a limit is breached",
      ]}
    />
  );
}

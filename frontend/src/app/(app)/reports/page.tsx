import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Reports" };

export default function Page() {
  return (
    <PlannedPage
      title="Reports"
      summary="Valuation, transaction and performance reports you can keep."
      phase="phase 2"
      features={[
        "Report on any portfolio and date range",
        "Separate realised and unrealised gains",
        "Export to CSV, Excel and PDF",
      ]}
    />
  );
}

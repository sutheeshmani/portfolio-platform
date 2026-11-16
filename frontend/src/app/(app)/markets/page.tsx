import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Markets" };

export default function Page() {
  return (
    <PlannedPage
      title="Markets"
      summary="Index levels and market movements for the ASX and US exchanges."
      phase="phase 2"
      features={[
        "Follow the ASX 200, S&P 500 and NASDAQ 100",
        "See trading hours and holidays for each exchange",
        "Check how fresh each price is and where it came from",
      ]}
    />
  );
}

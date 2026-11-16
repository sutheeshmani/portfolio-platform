import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "Stock research" };

export default function Page() {
  return (
    <PlannedPage
      title="Stock research"
      summary="Company financials and charts for any ASX or US share."
      phase="phase 2"
      features={[
        "Read income statements, balance sheets and cash flow",
        "Compare valuation, profitability and growth ratios",
        "View candlestick charts with moving averages, RSI and MACD",
      ]}
    />
  );
}

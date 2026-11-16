import type { Metadata } from "next";

import { PlannedPage } from "@/components/PlannedPage";

export const metadata: Metadata = { title: "AI investment assistant" };

export default function Page() {
  return (
    <PlannedPage
      title="AI investment assistant"
      summary="Ask questions about your portfolio and the companies you hold."
      phase="phase 4"
      features={[
        "Ask why your portfolio moved, in plain language",
        "Get structured research on a company, with sources and dates",
        "See bull, base and bear scenarios, clearly marked as analysis rather than advice",
      ]}
    />
  );
}

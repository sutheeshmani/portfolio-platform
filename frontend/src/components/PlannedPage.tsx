import { PageHeader } from "./ui";

/** Placeholder for a section whose back end isn't built yet. */
export function PlannedPage({
  title,
  summary,
  features,
  phase,
  simulated = false,
}: {
  title: string;
  summary: string;
  features: string[];
  phase: string;
  simulated?: boolean;
}) {
  return (
    <>
      {simulated && (
        <div className="hatch mb-6 rounded border border-stale/40 px-4 py-2 text-sm font-medium text-stale">
          Simulated money only. Paper trades never reach a broker and never change your real
          holdings.
        </div>
      )}
      <PageHeader title={title} description={summary} />
      <div className="rounded border border-line bg-surface p-6">
        <p className="font-semibold">Not built yet</p>
        <p className="mt-1 text-ink-soft">Planned for {phase} of the roadmap. It will let you:</p>
        <ul className="mt-4 list-disc space-y-1.5 pl-5">
          {features.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </div>
    </>
  );
}

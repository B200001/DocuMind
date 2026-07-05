import { CheckCircle2, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { JobStatus } from "@/lib/types";

type StepKey = "queued" | "parsing" | "embedding" | "ready";
type StepState = "done" | "active" | "pending";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "parsing", label: "Parsing" },
  { key: "embedding", label: "Embedding" },
  { key: "ready", label: "Ready" },
];

/**
 * Maps the backend's coarse JobStatus (queued | running | completed) to
 * the 4 stages the product wants to show.
 *
 * HONESTY NOTE: the backend does not currently distinguish "parsing" from
 * "embedding" — both happen while status is "running". Rather than fake a
 * distinction with a timer, we show both steps as simultaneously active
 * while running — an honest reflection of what we actually know.
 */
function computeStepStates(
  jobStatus: "queued" | "running" | "completed" | null
): Record<StepKey, StepState> {
  switch (jobStatus) {
    case null:
    case "queued":
      return { queued: "active", parsing: "pending", embedding: "pending", ready: "pending" };
    case "running":
      return { queued: "done", parsing: "active", embedding: "active", ready: "pending" };
    case "completed":
      return { queued: "done", parsing: "done", embedding: "done", ready: "done" };
  }
}

export function IngestStepper({
  jobStatus,
}: {
  jobStatus: Exclude<JobStatus, "failed"> | null;
}) {
  const states = computeStepStates(jobStatus);

  return (
    <ol className="flex items-center gap-1">
      {STEPS.map((step, i) => {
        const state = states[step.key];
        const isLast = i === STEPS.length - 1;

        return (
          <li key={step.key} className="flex items-center gap-1">
            <div className="flex items-center gap-1.5">
              <StepIcon state={state} />
              <span
                className={cn(
                  "text-xs whitespace-nowrap",
                  state === "pending" ? "text-muted-foreground" : "text-foreground",
                  state === "active" && "font-medium"
                )}
              >
                {step.label}
              </span>
            </div>
            {!isLast && (
              <span
                aria-hidden
                className={cn(
                  "mx-1 h-px w-4",
                  state === "done" ? "bg-success" : "bg-border"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") {
    return <CheckCircle2 className="size-3.5 text-success" />;
  }
  if (state === "active") {
    return <Loader2 className="size-3.5 animate-spin text-primary" />;
  }
  return <span className="size-3.5 rounded-full border border-border" aria-hidden />;
}

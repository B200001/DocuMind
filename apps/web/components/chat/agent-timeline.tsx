import { CheckCircle2, ListTree, Loader2, PenLine, Search, ShieldCheck, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TimelineNode, TimelineNodeState } from "@/components/chat/types";

const TIMELINE_STEPS: { key: TimelineNode; label: string; icon: LucideIcon }[] = [
  { key: "plan", label: "Plan", icon: ListTree },
  { key: "retrieve", label: "Retrieve", icon: Search },
  { key: "generate", label: "Generate", icon: PenLine },
  { key: "critic", label: "Critic", icon: ShieldCheck },
];

/**
 * Live chip row showing Plan → Retrieve → Generate → Critic progress.
 *
 * States come directly from node_start (-> "active") and tool_result
 * (-> "done") events, so a critic-triggered retrieval loop naturally
 * re-lights Retrieve/Generate/Critic — this isn't hardcoded, it just
 * reflects whatever the graph actually did.
 */
export function AgentTimeline({
  nodeStates,
  loops,
}: {
  nodeStates: Record<TimelineNode, TimelineNodeState>;
  loops: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {TIMELINE_STEPS.map(({ key, label, icon: Icon }) => {
        const state = nodeStates[key];
        return (
          <span
            key={key}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              state === "done" && "border-success/30 bg-success/10 text-success",
              state === "active" && "border-primary/30 bg-primary/10 text-primary",
              state === "pending" && "border-border text-muted-foreground"
            )}
          >
            {state === "active" ? (
              <Loader2 className="size-3 animate-spin" />
            ) : state === "done" ? (
              <CheckCircle2 className="size-3" />
            ) : (
              <Icon className="size-3" />
            )}
            {label}
          </span>
        );
      })}
      {loops > 1 && (
        <Badge variant="outline" className="text-xs">
          Refined search &times;{loops - 1}
        </Badge>
      )}
    </div>
  );
}

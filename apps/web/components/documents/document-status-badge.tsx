import * as React from "react";
import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/lib/types";

const STATUS_META: Record<
  DocumentStatus,
  { label: string; variant: "outline" | "secondary" | "success" | "destructive"; icon: React.ElementType }
> = {
  pending: { label: "Pending", variant: "outline", icon: Clock },
  ingesting: { label: "Processing", variant: "secondary", icon: Loader2 },
  ready: { label: "Ready", variant: "success", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "destructive", icon: XCircle },
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;

  return (
    <Badge variant={meta.variant}>
      <Icon className={status === "ingesting" ? "animate-spin" : undefined} />
      {meta.label}
    </Badge>
  );
}

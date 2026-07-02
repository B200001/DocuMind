"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { HealthResponse, ServiceHealthStatus } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_INTERVAL_MS = 30_000;

const DOT_COLOR: Record<ServiceHealthStatus, string> = {
  ok: "bg-success",
  degraded: "bg-primary",
  error: "bg-destructive",
};

const LABEL: Record<ServiceHealthStatus, string> = {
  ok: "All systems ready",
  degraded: "Degraded",
  error: "Unavailable",
};

/**
 * Small status dot + label in the sidebar footer, reflecting GET /health.
 * Polls every 30s. Fails soft: a network error is treated as "error"
 * rather than crashing the sidebar.
 */
export function StatusIndicator() {
  const [status, setStatus] = React.useState<ServiceHealthStatus | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
        const body: HealthResponse = await res.json();
        if (!cancelled) setStatus(body.status);
      } catch {
        if (!cancelled) setStatus("error");
      }
    }

    check();
    const id = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const displayStatus = status ?? "degraded";

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-sidebar-foreground/70">
      <span className="relative flex size-2">
        {status === "ok" && (
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
              DOT_COLOR[displayStatus]
            )}
          />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            status === null ? "bg-muted-foreground/40" : DOT_COLOR[displayStatus]
          )}
        />
      </span>
      <span>{status === null ? "Checking\u2026" : LABEL[displayStatus]}</span>
    </div>
  );
}

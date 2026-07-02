"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/lib/nav";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { StatusIndicator } from "@/components/layout/status-indicator";

/**
 * Primary sidebar navigation.
 *
 * Signature detail: the active item shows a small amber tab protruding
 * from the left edge, evoking a library card-catalog index tab — a nod
 * to the product's job of indexing and citing documents, rather than a
 * generic filled-pill active state.
 */
export function Sidebar({ className }: { className?: string }) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex h-full w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
        className
      )}
    >
      {/* Wordmark */}
      <div className="flex h-14 items-center px-5">
        <span className="font-display text-lg tracking-tight text-sidebar-foreground">
          documind
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2.5 py-2">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href || pathname?.startsWith(item.href + "/");
            const Icon = item.icon;

            return (
              <li key={item.href} className="relative">
                {/* The index-tab: a small protruding amber flag on the active item */}
                {active && (
                  <span
                    aria-hidden
                    className="absolute top-1/2 -left-2.5 h-5 w-1.5 -translate-y-1/2 rounded-r-full bg-sidebar-primary"
                  />
                )}
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/75 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                  )}
                >
                  <Icon className="size-4" />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer: theme toggle + service status */}
      <div className="border-t border-sidebar-border px-2.5 py-2.5">
        <div className="flex items-center justify-between px-1.5">
          <StatusIndicator />
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

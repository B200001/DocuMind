import * as React from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ScrollArea } from "@/components/ui/scroll-area";

/**
 * Top-level page shell: a fixed sidebar on desktop (>= md), a top bar with
 * a slide-out Sheet nav on mobile, and a scrollable main content area.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar className="hidden md:flex" />

      <div className="flex min-w-0 flex-1 flex-col">
        <MobileNav />
        <ScrollArea className="flex-1">
          <main className="mx-auto w-full max-w-5xl px-6 py-8 md:px-10">
            {children}
          </main>
        </ScrollArea>
      </div>
    </div>
  );
}

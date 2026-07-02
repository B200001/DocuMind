"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/lib/nav";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { StatusIndicator } from "@/components/layout/status-indicator";

/**
 * Mobile navigation: a top bar with a menu trigger that opens the same
 * nav items in a Sheet sliding in from the left. Only rendered below the
 * `md` breakpoint — see AppShell.
 */
export function MobileNav() {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);

  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-4 md:hidden">
      <span className="font-display text-lg tracking-tight">documind</span>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Open navigation">
            <Menu className="size-5" />
          </Button>
        </SheetTrigger>
        <SheetContent
          side="left"
          className="w-64 bg-sidebar text-sidebar-foreground border-sidebar-border p-0"
        >
          <SheetHeader className="h-14 justify-center border-b border-sidebar-border">
            <SheetTitle className="font-display text-lg font-normal tracking-tight text-sidebar-foreground">
              documind
            </SheetTitle>
          </SheetHeader>

          <nav className="px-2.5 py-2">
            <ul className="flex flex-col gap-0.5">
              {NAV_ITEMS.map((item) => {
                const active =
                  pathname === item.href || pathname?.startsWith(item.href + "/");
                const Icon = item.icon;

                return (
                  <li key={item.href} className="relative">
                    {active && (
                      <span
                        aria-hidden
                        className="absolute top-1/2 -left-2.5 h-5 w-1.5 -translate-y-1/2 rounded-r-full bg-sidebar-primary"
                      />
                    )}
                    <Link
                      href={item.href}
                      onClick={() => setOpen(false)}
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

          <div className="mt-auto border-t border-sidebar-border px-2.5 py-2.5">
            <div className="flex items-center justify-between px-1.5">
              <StatusIndicator />
              <ThemeToggle />
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </header>
  );
}

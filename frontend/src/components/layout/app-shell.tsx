"use client";

import * as React from "react";
import Link from "next/link";
import { Activity, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { NavLinks } from "@/components/layout/nav-items";
import { VehicleSelector } from "@/components/layout/vehicle-selector";
import { ThemeToggle, UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { useAuthGuard } from "@/hooks/use-auth-guard";
import { ErrorState } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-error";
import { cn } from "@/lib/utils";

/**
 * Authenticated application shell.
 *
 * Desktop: collapsible sidebar + sticky top bar.
 * Mobile: off-canvas drawer driven by a real dialog semantics implementation.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { status } = useAuthGuard();
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);

  const closeMobileNav = React.useCallback(() => setMobileNavOpen(false), []);

  // Escape closes the drawer; body scroll is locked while it is open.
  React.useEffect(() => {
    if (!mobileNavOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMobileNav();
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [mobileNavOpen, closeMobileNav]);

  if (status === "loading") {
    return <AppShellSkeleton />;
  }

  return (
    <div className="min-h-dvh bg-canvas">
      {/* Desktop sidebar ------------------------------------------------ */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-line bg-surface transition-[width] duration-200 lg:flex",
          sidebarCollapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-line px-3">
          <Link href="/dashboard" className="flex items-center gap-2 rounded-md">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-signal-500/15 text-signal-400">
              <Activity className="size-4" aria-hidden />
            </span>
            {!sidebarCollapsed ? (
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold tracking-tight text-ink">
                  Digital Twin
                </span>
                <span className="block truncate text-[0.65rem] text-ink-subtle">
                  Vehicle intelligence
                </span>
              </span>
            ) : null}
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto p-2 scrollbar-slim">
          <NavLinks />
        </div>

        <div className="border-t border-line p-2">
          <Button
            variant="ghost"
            size={sidebarCollapsed ? "iconSm" : "sm"}
            className={cn(sidebarCollapsed ? "w-full" : "w-full justify-start")}
            onClick={() => setSidebarCollapsed((value) => !value)}
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen aria-hidden />
            ) : (
              <>
                <PanelLeftClose aria-hidden />
                Collapse
              </>
            )}
          </Button>
        </div>
      </aside>

      {/* Mobile drawer -------------------------------------------------- */}
      {mobileNavOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/70"
            onClick={closeMobileNav}
            aria-hidden
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 flex w-[17rem] max-w-[85vw] flex-col border-r border-line bg-surface shadow-[var(--shadow-pop)] animate-fade-rise"
          >
            <div className="flex h-14 items-center justify-between gap-2 border-b border-line px-3">
              <span className="flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-lg bg-signal-500/15 text-signal-400">
                  <Activity className="size-4" aria-hidden />
                </span>
                <span className="text-sm font-semibold text-ink">Digital Twin</span>
              </span>
              <Button
                variant="ghost"
                size="iconSm"
                onClick={closeMobileNav}
                aria-label="Close navigation"
              >
                <X aria-hidden />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 scrollbar-slim">
              <NavLinks onNavigate={closeMobileNav} />
            </div>
          </div>
        </div>
      ) : null}

      {/* Main column ----------------------------------------------------- */}
      <div
        className={cn(
          "flex min-h-dvh flex-col transition-[padding] duration-200",
          sidebarCollapsed ? "lg:pl-16" : "lg:pl-60",
        )}
      >
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line bg-[color:color-mix(in_oklab,var(--canvas)_88%,transparent)] px-3 backdrop-blur sm:px-4">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
          >
            <Menu aria-hidden />
          </Button>

          <div className="hidden sm:block">
            <VehicleSelector />
          </div>
          <div className="sm:hidden">
            <VehicleSelector compact />
          </div>

          <div className="ml-auto flex items-center gap-1.5">
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>

        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 px-3 py-5 focus:outline-none sm:px-5 sm:py-6"
        >
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>

        <footer className="border-t border-line px-4 py-4 text-center text-[0.7rem] text-ink-subtle">
          Digital Twin — vehicle health intelligence. Scores come from a deterministic
          rule engine; AI interpretation is labelled separately and never replaces data.
        </footer>
      </div>
    </div>
  );
}

function AppShellSkeleton() {
  return (
    <div className="min-h-dvh bg-canvas">
      <div className="flex min-h-dvh">
        <div className="hidden w-60 shrink-0 border-r border-line bg-surface lg:block">
          <div className="flex h-14 items-center gap-2 border-b border-line px-3">
            <Skeleton className="size-8 rounded-lg" />
            <Skeleton className="h-3 w-28" />
          </div>
          <div className="space-y-2 p-3">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        </div>
        <div className="flex-1">
          <div className="flex h-14 items-center gap-3 border-b border-line px-4">
            <Skeleton className="h-8 w-40" />
            <div className="ml-auto">
              <Skeleton className="size-8 rounded-md" />
            </div>
          </div>
          <div className="space-y-4 p-6">
            <Skeleton className="h-6 w-56" />
            <div className="grid gap-4 lg:grid-cols-3">
              <Skeleton className="h-44 lg:col-span-1" />
              <Skeleton className="h-44 lg:col-span-2" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-24" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Admin-only wrapper for the admin area. The backend also enforces this (403 on
 * every admin endpoint); this only avoids rendering a page the user cannot use.
 */
export function AuthenticatedShell({
  children,
  requireAdmin = false,
}: {
  children: React.ReactNode;
  requireAdmin?: boolean;
}) {
  const { status, isAdmin } = useAuthGuard({ requireAdmin });

  if (requireAdmin && status === "authenticated" && !isAdmin) {
    return (
      <div className="mx-auto max-w-lg py-16">
        <ErrorState error={new ApiError(403, "Admin privileges required")} />
      </div>
    );
  }

  return <>{children}</>;
}

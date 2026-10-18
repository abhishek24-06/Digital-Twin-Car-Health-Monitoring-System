"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  Car,
  CirclePlay,
  Gauge,
  GitBranch,
  LayoutDashboard,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
  type LucideIcon,
} from "lucide-react";
import { useSessionStore } from "@/lib/session-store";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
  adminOnly?: boolean;
}

/**
 * The four fleet-level sections promoted into the persistent top header. These
 * are the primary destinations; the sidebar deliberately does **not** repeat
 * them, so a page is never listed twice.
 */
export const SECTION_ITEMS: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: "Fleet",
    icon: LayoutDashboard,
    description: "Fleet-level health, telemetry and attention",
  },
  {
    href: "/simulations",
    label: "Simulation Control",
    icon: CirclePlay,
    description: "Start and stop per-vehicle data simulators",
  },
  {
    href: "/workflow",
    label: "Workflow Monitor",
    icon: GitBranch,
    description: "Real-time observability of system pipelines",
  },
  {
    href: "/rag",
    label: "Knowledge Search",
    icon: BookOpen,
    description: "Search ingested documentation",
  },
];

/**
 * Sidebar destinations: only the account-scoped pages the header does not
 * already provide. `/simulations`, `/workflow`, `/rag` and `/dashboard` used to
 * live here too; they now live in the header so the same link is not rendered
 * twice.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/vehicles",
    label: "My Vehicles",
    icon: Car,
    description: "Register and manage vehicles",
  },
  {
    href: "/profile",
    label: "Profile",
    icon: UserIcon,
    description: "Account details",
  },
];

export const ADMIN_NAV_ITEM: NavItem = {
  href: "/admin/rag",
  label: "Admin A� RAG corpus",
  icon: ShieldCheck,
  description: "Corpus health and document management",
  adminOnly: true,
};

/** Vehicle-scoped tabs, rendered inside the vehicle workspace header. */
export const VEHICLE_TABS = [
  { href: "", label: "Overview", icon: Gauge },
  { href: "/health", label: "Live Health", icon: Activity },
  { href: "/simulation", label: "Simulation", icon: CirclePlay },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/telemetry", label: "Telemetry", icon: Activity },
  { href: "/diagnosis", label: "AI Diagnosis", icon: Sparkles },
  { href: "/history", label: "History", icon: Activity },
  { href: "/alerts", label: "Alerts", icon: Bell },
] as const;

/**
 * Single source of truth for "which nav entry is the current page", used by
 * both the header tabs and the sidebar. The active state is always derived from
 * the URL, never stored separately, so a refresh or a deep link cannot leave it
 * out of sync.
 *
 * Nested routes keep their parent active (e.g. `/vehicles/<id>/health` keeps
 * My Vehicles active), except the fleet overview, which is a leaf route and must
 * not light up for unrelated paths. `/admin/rag` is a distinct page and does not
 * activate the Knowledge Search tab.
 */
export function isNavActive(pathname: string | null | undefined, href: string): boolean {
  if (!pathname) return false;
  if (pathname === href) return true;
  if (href === "/dashboard") return false;
  return pathname.startsWith(`${href}/`);
}

/**
 * Horizontal section tabs for the top header, plus a vertical variant reused by
 * the mobile navigation drawer. The active tab is derived from the current
 * route via `isNavActive`.
 */
export function HeaderNav({
  onNavigate,
  className,
  orientation = "horizontal",
}: {
  onNavigate?: () => void;
  className?: string;
  orientation?: "horizontal" | "vertical";
}) {
  const pathname = usePathname();
  const isVertical = orientation === "vertical";

  return (
    <nav
      aria-label="Main sections"
      className={cn(
        "flex",
        isVertical
          ? "flex-col gap-0.5"
          : "min-w-0 flex-row items-center gap-0.5 overflow-x-auto scrollbar-slim",
        className,
      )}
    >
      {SECTION_ITEMS.map((item) => {
        const active = isNavActive(pathname, item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            title={item.label}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex shrink-0 items-center rounded-md text-sm transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
              isVertical ? "w-full gap-3 px-3 py-2" : "gap-2 px-2 py-1.5",
              active
                ? "bg-surface-3 text-ink shadow-[var(--shadow-panel)]"
                : "text-ink-muted hover:bg-surface-2 hover:text-ink",
            )}
          >
            <Icon
              className={cn(
                "size-4 shrink-0",
                active ? "text-signal-400" : "text-ink-subtle group-hover:text-ink-muted",
              )}
              aria-hidden
            />
            {/* Desktop tabs collapse to icons below xl so the header never
                overlaps the profile at narrower widths; the label is always the
                accessible name via `aria-label`. */}
            <span
              className={cn(
                isVertical ? "truncate" : "hidden whitespace-nowrap xl:inline",
              )}
            >
              {item.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

export function NavLinks({
  onNavigate,
  className,
}: {
  onNavigate?: () => void;
  className?: string;
}) {
  const pathname = usePathname();
  const isAdmin = useSessionStore((state) => state.user?.role === "admin");
  const items = isAdmin ? [...NAV_ITEMS, ADMIN_NAV_ITEM] : NAV_ITEMS;

  return (
    <nav
      aria-label="Primary"
      className={cn("flex flex-col gap-0.5", className)}
    >
      {items.map((item) => {
        const active = isNavActive(pathname, item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
              active
                ? "bg-surface-3 text-ink shadow-[var(--shadow-panel)]"
                : "text-ink-muted hover:bg-surface-2 hover:text-ink",
            )}
          >
            <Icon
              className={cn(
                "size-4 shrink-0",
                active ? "text-signal-400" : "text-ink-subtle group-hover:text-ink-muted",
              )}
              aria-hidden
            />
            <span className="truncate">{item.label}</span>
            {item.adminOnly ? (
              <span className="ml-auto rounded border border-line px-1 text-[0.6rem] uppercase tracking-wider text-ink-subtle">
                admin
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

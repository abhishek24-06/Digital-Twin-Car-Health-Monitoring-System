"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpen,
  Car,
  Gauge,
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

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Fleet overview and current health",
  },
  {
    href: "/vehicles",
    label: "My Vehicles",
    icon: Car,
    description: "Register and manage vehicles",
  },
  {
    href: "/rag",
    label: "Manufacturer Guidance",
    icon: BookOpen,
    description: "Search ingested documentation",
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
  label: "Admin · RAG corpus",
  icon: ShieldCheck,
  description: "Corpus health and document management",
  adminOnly: true,
};

/** Vehicle-scoped tabs, rendered inside the vehicle workspace header. */
export const VEHICLE_TABS = [
  { href: "", label: "Overview", icon: Gauge },
  { href: "/health", label: "Health", icon: Activity },
  { href: "/telemetry", label: "Telemetry", icon: Activity },
  { href: "/diagnosis", label: "AI Diagnosis", icon: Sparkles },
  { href: "/history", label: "History", icon: Activity },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/dashboard";
  if (href === "/vehicles") {
    return pathname === "/vehicles" || pathname.startsWith("/vehicles/");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
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
        const active = isActive(pathname, item.href);
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
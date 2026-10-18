"use client";

import Link from "next/link";
import {
  Activity,
  BellRing,
  Car,
  CirclePlay,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { FleetTotals } from "@/types/api";

export interface KpiDefinition {
  key: string;
  label: string;
  value: number;
  /** Optional qualifier shown next to the value, e.g. "of 4". */
  unit?: string;
  /** One-line, plain-language definition of what the number counts. */
  hint: string;
  href: string;
  icon: LucideIcon;
  tone: "neutral" | "healthy" | "attention" | "critical";
}

/**
 * The fleet KPIs, each derived from a real signal and labelled so its meaning
 * is unambiguous:
 *
 * * Registered vehicles — how many this account can access.
 * * Telemetry live — vehicles whose newest sample is inside the freshness window.
 * * Needs attention — active warning/critical alert, or a *current*
 *   attention/critical assessment (an aged assessment never counts).
 * * Open alerts — open + acknowledged alerts across the fleet.
 * * Active simulators — simulators starting, running or stopping.
 */
export function fleetKpiDefinitions(totals: FleetTotals): KpiDefinition[] {
  return [
    {
      key: "vehicles",
      label: "Registered vehicles",
      value: totals.vehicles,
      hint: "Vehicles you can access.",
      href: "/vehicles",
      icon: Car,
      tone: "neutral",
    },
    {
      key: "recent",
      label: "Telemetry live",
      value: totals.vehicles_with_recent_telemetry,
      unit: `of ${totals.vehicles}`,
      hint: "Vehicles with a sample inside the freshness window.",
      href: "#fleet",
      icon: Activity,
      tone: totals.vehicles_with_recent_telemetry > 0 ? "healthy" : "neutral",
    },
    {
      key: "attention",
      label: "Needs attention",
      value: totals.vehicles_requiring_attention,
      hint: "Active alert, or a current attention/critical assessment.",
      href: "#fleet-attention",
      icon: TriangleAlert,
      tone: totals.vehicles_requiring_attention > 0 ? "attention" : "healthy",
    },
    {
      key: "alerts",
      label: "Open alerts",
      value: totals.open_alerts,
      hint:
        totals.critical_open_alerts > 0
          ? `${totals.critical_open_alerts} of them critical.`
          : "Open or acknowledged alerts across the fleet.",
      href: "#fleet-attention",
      icon: BellRing,
      tone:
        totals.critical_open_alerts > 0
          ? "critical"
          : totals.open_alerts > 0
            ? "attention"
            : "healthy",
    },
    {
      key: "sims",
      label: "Active simulators",
      value: totals.active_simulations,
      hint: "Starting, running or stopping right now.",
      href: "/simulations",
      icon: CirclePlay,
      tone: totals.active_simulations > 0 ? "healthy" : "neutral",
    },
  ];
}

const TONE_TEXT: Record<KpiDefinition["tone"], string> = {
  neutral: "text-ink",
  healthy: "text-[color:var(--color-healthy)]",
  attention: "text-[color:var(--color-attention)]",
  critical: "text-[color:var(--color-critical)]",
};

function KpiCard({ definition }: { definition: KpiDefinition }) {
  const { icon: Icon, href, tone } = definition;
  const inner = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.7rem] font-medium uppercase tracking-wider text-ink-subtle">
          {definition.label}
        </span>
        <Icon className="size-4 text-ink-subtle" aria-hidden />
      </div>
      <p className={cn("tabular mt-2 text-2xl font-semibold tracking-tight", TONE_TEXT[tone])}>
        {definition.value.toLocaleString()}
        {definition.unit ? (
          <span className="ml-1 text-xs font-normal text-ink-subtle">{definition.unit}</span>
        ) : null}
      </p>
      <p className="mt-1 text-[0.7rem] leading-relaxed text-ink-subtle">{definition.hint}</p>
    </>
  );

  const className =
    "block rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-panel)] transition-colors hover:border-[color:color-mix(in_oklab,var(--color-signal-500)_35%,transparent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-signal-500)]";

  // Hash links scroll within the page and are plain anchors; route links use the
  // client router.
  if (href.startsWith("#")) {
    return (
      <a href={href} className={className} data-testid={`kpi-${definition.key}`}>
        {inner}
      </a>
    );
  }
  return (
    <Link href={href} className={className} data-testid={`kpi-${definition.key}`}>
      {inner}
    </Link>
  );
}

export function FleetKpis({ totals }: { totals: FleetTotals }) {
  return (
    <div
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
      aria-label="Fleet key performance indicators"
    >
      {fleetKpiDefinitions(totals).map((definition) => (
        <KpiCard key={definition.key} definition={definition} />
      ))}
    </div>
  );
}

export function FleetKpisSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {Array.from({ length: 5 }, (_, index) => (
        <Card key={index} className="p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-12" />
          <Skeleton className="mt-2 h-3 w-32" />
        </Card>
      ))}
    </div>
  );
}

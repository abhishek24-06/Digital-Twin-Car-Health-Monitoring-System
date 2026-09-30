import type { HealthStatus, Severity, ScopeTier } from "@/types/api";

/**
 * Metric metadata.
 *
 * Mirrors `app/intelligence/models.py::METRIC_UNITS` (the backend's single
 * source of truth for supported telemetry metrics) and adds presentation-only
 * labels, icons and axis hints. Adding a metric here that the backend does not
 * accept would be wrong, so the list is intentionally explicit.
 */

export interface MetricMeta {
  key: string;
  label: string;
  shortLabel: string;
  unit: string;
  /** Sensible chart domain; `null` means let the data decide. */
  domain?: [number, number];
  decimals: number;
  /** Dashboard headline metrics, in display order. */
  headline: boolean;
}

export const METRICS: readonly MetricMeta[] = [
  {
    key: "coolant_temperature",
    label: "Coolant temperature",
    shortLabel: "Coolant",
    unit: "°C",
    decimals: 1,
    headline: true,
  },
  {
    key: "oil_temperature",
    label: "Oil temperature",
    shortLabel: "Oil temp",
    unit: "°C",
    decimals: 1,
    headline: true,
  },
  {
    key: "battery_voltage",
    label: "Battery voltage",
    shortLabel: "Battery",
    unit: "V",
    decimals: 1,
    headline: true,
  },
  {
    key: "engine_load",
    label: "Engine load",
    shortLabel: "Load",
    unit: "%",
    domain: [0, 100],
    decimals: 1,
    headline: true,
  },
  {
    key: "rpm",
    label: "Engine speed",
    shortLabel: "RPM",
    unit: "rpm",
    decimals: 0,
    headline: true,
  },
  {
    key: "fuel_level",
    label: "Fuel level",
    shortLabel: "Fuel",
    unit: "%",
    domain: [0, 100],
    decimals: 1,
    headline: true,
  },
  {
    key: "speed",
    label: "Vehicle speed",
    shortLabel: "Speed",
    unit: "km/h",
    domain: [0, 260],
    decimals: 0,
    headline: false,
  },
  {
    key: "intake_air_temperature",
    label: "Intake air temperature",
    shortLabel: "Intake",
    unit: "°C",
    decimals: 1,
    headline: false,
  },
  {
    key: "throttle_position",
    label: "Throttle position",
    shortLabel: "Throttle",
    unit: "%",
    domain: [0, 100],
    decimals: 1,
    headline: false,
  },
  {
    key: "engine_runtime",
    label: "Engine runtime",
    shortLabel: "Runtime",
    unit: "s",
    decimals: 0,
    headline: false,
  },
  {
    key: "odometer",
    label: "Odometer",
    shortLabel: "Odometer",
    unit: "km",
    decimals: 1,
    headline: false,
  },
] as const;

const METRIC_INDEX: ReadonlyMap<string, MetricMeta> = new Map(
  METRICS.map((metric) => [metric.key, metric]),
);

export function metricMeta(key: string | null | undefined): MetricMeta | undefined {
  if (!key) return undefined;
  return METRIC_INDEX.get(key);
}

export function metricLabel(key: string | null | undefined): string {
  return metricMeta(key)?.label ?? key ?? "Unknown metric";
}

export function metricUnit(key: string | null | undefined): string {
  return metricMeta(key)?.unit ?? "";
}

export const HEADLINE_METRICS: readonly MetricMeta[] = METRICS.filter(
  (metric) => metric.headline,
);

export const TELEMETRY_METRICS: readonly MetricMeta[] = METRICS;

/* ------------------------------------------------------------------ */
/* Health status semantics                                             */
/* ------------------------------------------------------------------ */

export interface StatusSemantics {
  label: string;
  /** Tailwind text colour token. */
  text: string;
  /** Tailwind background token for badges/pills. */
  surface: string;
  border: string;
  /** Chart/stroke colour (CSS var). */
  color: string;
}

const HEALTH_STATUS: Record<HealthStatus, StatusSemantics> = {
  healthy: {
    label: "Healthy",
    text: "text-[color:var(--color-healthy)]",
    surface: "bg-[color:color-mix(in_oklab,var(--color-healthy)_16%,transparent)]",
    border: "border-[color:color-mix(in_oklab,var(--color-healthy)_42%,transparent)]",
    color: "var(--color-healthy)",
  },
  attention: {
    label: "Needs attention",
    text: "text-[color:var(--color-attention)]",
    surface: "bg-[color:color-mix(in_oklab,var(--color-attention)_16%,transparent)]",
    border: "border-[color:color-mix(in_oklab,var(--color-attention)_42%,transparent)]",
    color: "var(--color-attention)",
  },
  critical: {
    label: "Critical",
    text: "text-[color:var(--color-critical)]",
    surface: "bg-[color:color-mix(in_oklab,var(--color-critical)_16%,transparent)]",
    border: "border-[color:color-mix(in_oklab,var(--color-critical)_42%,transparent)]",
    color: "var(--color-critical)",
  },
  unknown: {
    label: "Unknown",
    text: "text-[color:var(--color-unknown)]",
    surface: "bg-[color:color-mix(in_oklab,var(--color-unknown)_16%,transparent)]",
    border: "border-[color:color-mix(in_oklab,var(--color-unknown)_42%,transparent)]",
    color: "var(--color-unknown)",
  },
};

export function healthStatus(status: HealthStatus | null | undefined): StatusSemantics {
  return HEALTH_STATUS[status ?? "unknown"];
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  info: "Information",
  warning: "Warning",
  critical: "Critical",
};

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

export const SCOPE_LABEL: Record<ScopeTier, string> = {
  EXACT_VEHICLE: "Exact vehicle",
  MODEL: "Model",
  MAKE: "Make",
  GENERIC: "Generic",
};

export const SCOPE_RANK: Record<ScopeTier, number> = {
  EXACT_VEHICLE: 3,
  MODEL: 2,
  MAKE: 1,
  GENERIC: 0,
};

/** Time ranges offered by the telemetry explorer, mapped to real API filters. */
export interface TimeRangeOption {
  key: string;
  label: string;
  minutes: number;
}

export const TIME_RANGES: readonly TimeRangeOption[] = [
  { key: "15m", label: "15 min", minutes: 15 },
  { key: "30m", label: "30 min", minutes: 30 },
  { key: "1h", label: "1 hour", minutes: 60 },
  { key: "6h", label: "6 hours", minutes: 360 },
  { key: "24h", label: "24 hours", minutes: 1440 },
] as const;

/** Analysis window options for `POST /health/analyze` (1–1440 per the API). */
export const ANALYSIS_WINDOWS: readonly number[] = [15, 30, 60, 360, 1440];
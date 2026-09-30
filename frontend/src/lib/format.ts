/**
 * Display formatting.
 *
 * All timestamps are rendered in the viewer's local timezone with an explicit
 * UTC suffix on the tooltip/label, because the backend always emits UTC.
 */

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFmt = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
});

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return timeFmt.format(date);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return dateTimeFmt.format(date);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return dateFmt.format(date);
}

/** Axis-friendly short stamp, e.g. `14:05`. */
export function formatAxisTime(iso: string | number): string {
  const date = new Date(iso);
  return timeFmt.format(date);
}

/** "3 min ago" / "in 2 h" — used for telemetry freshness. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  const deltaSeconds = (date.getTime() - Date.now()) / 1000;
  const abs = Math.abs(deltaSeconds);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

  if (abs < 45) return "just now";
  if (abs < 3600) return rtf.format(Math.round(deltaSeconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(deltaSeconds / 3600), "hour");
  if (abs < 604800) return rtf.format(Math.round(deltaSeconds / 86400), "day");
  return formatDate(iso);
}

/** Duration from seconds, e.g. `9m 40s`. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Metric-aware precision so 87.443°C does not pretend to be precise. */
export function formatMetricValue(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return "—";
  switch (unit) {
    case "C":
    case "V":
    case "%":
      return value.toFixed(1);
    case "RPM":
      return Math.round(value).toLocaleString();
    case "km":
      return value.toFixed(1);
    case "km/h":
    case "s":
      return Math.round(value).toLocaleString();
    default:
      return value.toFixed(2);
  }
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 0..1 → percentage string. Used for confidence and coverage. */
export function formatPercent(
  value: number | null | undefined,
  digits = 0,
): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** Mask a VIN for display: keep first 3 and last 3 characters. */
export function maskVin(vin: string): string {
  if (vin.length <= 6) return vin;
  return `${vin.slice(0, 3)}${"•".repeat(Math.min(vin.length - 6, 9))}${vin.slice(-3)}`;
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

/** Turn a snake_case backend key into a readable label. */
export function humanizeKey(key: string): string {
  return titleCase(key);
}
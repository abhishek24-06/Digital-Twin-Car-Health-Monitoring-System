/**
 * Presentation maps for the fleet overview.
 *
 * These translate the backend's *already-classified* states into a label and a
 * tone. They never re-derive freshness or attention: the backend owns those
 * rules (see `app/services/fleet_overview.py`), and the frontend only decides
 * how to show the answer. That keeps the dashboard from contradicting
 * Simulation Control or the workflow monitor.
 */

import type {
  AssessmentFreshness,
  FleetAssessmentSummary,
  FleetVehicleSummary,
  HealthStatus,
  SimulationState,
  TelemetryFreshness,
} from "@/types/api";

export type FleetTone =
  | "neutral"
  | "accent"
  | "healthy"
  | "attention"
  | "critical"
  | "unknown";

export interface FleetPresentation {
  label: string;
  tone: FleetTone;
  description: string;
}

export const TELEMETRY_FRESHNESS: Record<TelemetryFreshness, FleetPresentation> = {
  recent: {
    label: "Live",
    tone: "healthy",
    description: "Telemetry arrived within the freshness window.",
  },
  stale: {
    label: "Stale",
    tone: "attention",
    description: "Telemetry exists but is older than the freshness window.",
  },
  no_data: {
    label: "No data",
    tone: "neutral",
    description: "No telemetry has ever been stored for this vehicle.",
  },
  unknown: {
    label: "Unknown",
    tone: "unknown",
    description: "Telemetry freshness could not be determined.",
  },
};

export const ASSESSMENT_FRESHNESS: Record<AssessmentFreshness, FleetPresentation> = {
  fresh: {
    label: "Current",
    tone: "healthy",
    description: "Assessed within the health monitor's evaluation cadence.",
  },
  stale: {
    label: "Aged",
    tone: "attention",
    description:
      "This assessment is older than the monitor cadence — read it as history, not the current state.",
  },
  none: {
    label: "Not assessed",
    tone: "neutral",
    description: "This vehicle has not been scored yet.",
  },
};

export const SIMULATOR_STATE: Record<SimulationState, FleetPresentation> = {
  stopped: { label: "Stopped", tone: "neutral", description: "No simulator is running." },
  starting: { label: "Starting", tone: "accent", description: "The simulator is starting up." },
  running: {
    label: "Running",
    tone: "healthy",
    description: "The simulator is running and its feed is current.",
  },
  stopping: { label: "Stopping", tone: "accent", description: "The simulator is shutting down." },
  degraded: {
    label: "Degraded",
    tone: "attention",
    description: "The process is up but telemetry is not arriving as expected.",
  },
  error: { label: "Error", tone: "critical", description: "The simulator failed." },
};

/**
 * The vehicle-condition rating behind an assessment.
 *
 * A limited-data assessment carries a data-state `health_status` (e.g.
 * `limited_data`) and the real rating in `provisional_rating`; fall back to it
 * so a provisional `critical` is never read as neutral.
 */
export function assessmentRating(
  assessment: FleetAssessmentSummary | null,
): HealthStatus | null {
  if (!assessment) return null;
  if (assessment.provisional && assessment.provisional_rating) {
    return assessment.provisional_rating;
  }
  return assessment.health_status;
}

/** Whether a rating represents a condition that needs a human's attention. */
export function isAttentionRating(rating: HealthStatus | null): boolean {
  return rating === "attention" || rating === "critical";
}

/**
 * A short explanation of why a row is flagged. Driven by the backend's
 * `requires_attention` flag; the text is only ever a coarser restatement of the
 * same fields, so it can never disagree with the flag itself.
 */
export function attentionReason(row: FleetVehicleSummary): string | null {
  if (!row.requires_attention) return null;
  if (row.open_alerts > 0) {
    return `${row.open_alerts} active alert${row.open_alerts === 1 ? "" : "s"}`;
  }
  const rating = assessmentRating(row.assessment);
  if (row.assessment_freshness === "fresh" && rating === "critical") {
    return "Current assessment is critical";
  }
  if (row.assessment_freshness === "fresh" && rating === "attention") {
    return "Current assessment needs attention";
  }
  return "Flagged for attention";
}

/** Compose a vehicle's display name and secondary detail line. */
export function vehicleName(row: Pick<FleetVehicleSummary, "make" | "model">): string {
  return `${row.make} ${row.model}`;
}

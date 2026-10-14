import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricTile } from "@/components/health/metric-tile";
import { TEST_VEHICLE } from "@/test/utils";
import type { MetricStatistics, TelemetryResponse } from "@/types/api";

const BASE_TS = Date.parse("2026-10-14T02:31:30.000Z");

function sample(rpm: number, secondsOffset: number): TelemetryResponse {
  const timestamp = new Date(BASE_TS + secondsOffset * 1000).toISOString();
  return {
    id: `00000000-0000-4000-8000-${String(secondsOffset + 200).padStart(12, "0")}`,
    vehicle_id: TEST_VEHICLE.id,
    timestamp,
    rpm,
    speed: null,
    engine_load: null,
    coolant_temperature: null,
    oil_temperature: null,
    battery_voltage: null,
    fuel_level: null,
    intake_air_temperature: null,
    throttle_position: null,
    engine_runtime: null,
    odometer: null,
    raw_payload: null,
    source_event_id: null,
    created_at: timestamp,
  };
}

function statistics(): MetricStatistics {
  return {
    metric: "rpm",
    unit: "rpm",
    count: 3,
    minimum: 10,
    maximum: 30,
    mean: 20,
    median: 20,
    std_dev: 10,
    first: 10,
    last: 30,
    range: 20,
    percentile_25: 15,
    percentile_75: 25,
    coefficient_of_variation: 0.5,
  };
}

function points(): { x: number; y: number }[] {
  const polyline = document.querySelector("svg polyline");
  expect(polyline).not.toBeNull();
  return (polyline?.getAttribute("points") ?? "")
    .split(" ")
    .map((pair) => {
      const [x, y] = pair.split(",").map(Number);
      return { x, y };
    });
}

describe("MetricTile sparkline", () => {
  it("draws newest-first samples oldest-first along the x-axis", () => {
    // API order: newest (30) first, oldest (10) last.
    render(
      <MetricTile
        metric="rpm"
        latest={null}
        statistics={statistics()}
        samples={[sample(30, 20), sample(20, 10), sample(10, 0)]}
      />,
    );

    expect(screen.getByText("30")).toBeInTheDocument();
    const [first, , last] = points();
    // Chronological rise 10 -> 30: the trace climbs upward (smaller y) left to right.
    expect(first.x).toBeLessThan(last.x);
    expect(first.y).toBeGreaterThan(last.y);
  });
});

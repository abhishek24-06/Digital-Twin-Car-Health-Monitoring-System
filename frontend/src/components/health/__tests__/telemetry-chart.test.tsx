import { describe, expect, it } from "vitest";
import {
  axisIdForUnit,
  buildChartRows,
  groupMetricsByUnit,
} from "@/components/health/telemetry-chart";
import { HEADLINE_METRICS, METRICS, metricMeta } from "@/lib/metrics";
import type { TelemetryResponse } from "@/types/api";

const BASE_TS = Date.parse("2026-10-14T02:31:30.000Z");

function sample(
  secondsOffset: number,
  overrides: Partial<TelemetryResponse> = {},
): TelemetryResponse {
  return {
    id: `00000000-0000-4000-8000-${String(secondsOffset + 100).padStart(12, "0")}`,
    vehicle_id: "00000000-0000-4000-8000-000000000000",
    timestamp: new Date(BASE_TS + secondsOffset * 1000).toISOString(),
    rpm: 3000,
    speed: 80,
    engine_load: 40,
    coolant_temperature: 90,
    oil_temperature: 88,
    battery_voltage: 14,
    fuel_level: 60,
    intake_air_temperature: 30,
    throttle_position: 25,
    engine_runtime: 5000,
    odometer: 80000,
    raw_payload: null,
    source_event_id: null,
    created_at: new Date(BASE_TS + secondsOffset * 1000).toISOString(),
    ...overrides,
  };
}

describe("groupMetricsByUnit", () => {
  it("isolates rpm on its own axis, away from temperature and voltage", () => {
    const groups = groupMetricsByUnit(HEADLINE_METRICS.map((metric) => metric.key));

    const axisOf = (key: string) =>
      axisIdForUnit(metricMeta(key)?.unit ?? "");
    const rpmAxis = axisOf("rpm");
    expect(rpmAxis).not.toBe(axisOf("coolant_temperature"));
    expect(rpmAxis).not.toBe(axisOf("oil_temperature"));
    expect(rpmAxis).not.toBe(axisOf("battery_voltage"));

    const rpmGroup = groups.find((group) => group.unit === "rpm");
    expect(rpmGroup?.metrics).toEqual(["rpm"]);
  });

  it("shares one axis per unit and keeps selection order", () => {
    const groups = groupMetricsByUnit([
      "coolant_temperature",
      "oil_temperature",
      "battery_voltage",
      "rpm",
    ]);
    expect(groups.map((group) => group.unit)).toEqual(["°C", "V", "rpm"]);
    expect(groups[0].metrics).toEqual(["coolant_temperature", "oil_temperature"]);
  });

  it("applies a shared explicit domain only when every metric agrees", () => {
    const percent = groupMetricsByUnit(["engine_load", "fuel_level"]);
    expect(percent).toHaveLength(1);
    expect(percent[0].domain).toEqual([0, 100]);

    // °C metrics declare no domain, so the data decides.
    const temps = groupMetricsByUnit(["coolant_temperature", "oil_temperature"]);
    expect(temps[0].domain).toBeUndefined();
  });

  it("puts unknown metrics on their own fallback axis", () => {
    const groups = groupMetricsByUnit(["rpm", "not_a_metric"]);
    expect(groups.map((group) => group.unit)).toEqual(["rpm", ""]);
  });
});

describe("buildChartRows", () => {
  it("orders newest-first API samples oldest-first for the x-axis", () => {
    const rows = buildChartRows(
      [sample(20), sample(0), sample(10)],
      ["rpm", "coolant_temperature"],
    );
    expect(rows.map((row) => row.ts)).toEqual([BASE_TS, BASE_TS + 10_000, BASE_TS + 20_000]);
    expect(rows[0].rpm).toBe(3000);
  });

  it("derives the x value from the sample timestamp field", () => {
    const rows = buildChartRows([sample(5)], ["rpm"]);
    expect(rows[0].ts).toBe(Date.parse("2026-10-14T02:31:35.000Z"));
  });

  it("maps non-numeric and unknown fields to gaps", () => {
    const rows = buildChartRows(
      [sample(0, { rpm: null, coolant_temperature: 91.5 })],
      ["rpm", "coolant_temperature", "not_a_metric"],
    );
    expect(rows[0].rpm).toBeNull();
    expect(rows[0].coolant_temperature).toBe(91.5);
    expect(rows[0].not_a_metric).toBeNull();
  });
});

describe("chart series field mapping", () => {
  it("covers every persisted sensor field with the right unit and precision", () => {
    const expected: Record<string, { unit: string; decimals: number }> = {
      coolant_temperature: { unit: "°C", decimals: 1 },
      oil_temperature: { unit: "°C", decimals: 1 },
      battery_voltage: { unit: "V", decimals: 1 },
      engine_load: { unit: "%", decimals: 1 },
      rpm: { unit: "rpm", decimals: 0 },
      fuel_level: { unit: "%", decimals: 1 },
      speed: { unit: "km/h", decimals: 0 },
      intake_air_temperature: { unit: "°C", decimals: 1 },
      throttle_position: { unit: "%", decimals: 1 },
      engine_runtime: { unit: "s", decimals: 0 },
      odometer: { unit: "km", decimals: 1 },
    };
    expect(METRICS.map((metric) => metric.key).sort()).toEqual(
      Object.keys(expected).sort(),
    );
    for (const [key, mapping] of Object.entries(expected)) {
      expect(metricMeta(key)?.unit).toBe(mapping.unit);
      expect(metricMeta(key)?.decimals).toBe(mapping.decimals);
    }
  });
});

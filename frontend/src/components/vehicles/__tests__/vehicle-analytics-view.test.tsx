import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { VehicleAnalyticsView } from "@/components/vehicles/vehicle-analytics-view";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";
import { useHistoricalAnalytics } from "@/hooks/use-vehicle-data";
import type { HistoricalAnalyticsResponse } from "@/types/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: TEST_VEHICLE.id }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/1/analytics",
}));

vi.mock("@/hooks/use-vehicle-data", async () => {
  const actual = await vi.importActual<
    typeof import("@/hooks/use-vehicle-data")
  >("@/hooks/use-vehicle-data");
  return {
    ...actual,
    useHistoricalAnalytics: vi.fn(),
  };
});

function analytics(
  overrides: Partial<HistoricalAnalyticsResponse> = {},
): HistoricalAnalyticsResponse {
  return {
    vehicle_id: TEST_VEHICLE.id,
    range: "24h",
    window_start: "2026-01-01T00:00:00Z",
    window_end: "2026-01-02T00:00:00Z",
    duration_seconds: 86400,
    timezone: "UTC",
    total_samples: 3,
    earliest_sample_at: "2026-01-01T00:00:01Z",
    latest_sample_at: "2026-01-01T00:00:03Z",
    metrics: [
      {
        metric: "engine_rpm",
        valid_samples: 3,
        min_value: 1000,
        max_value: 3000,
        mean_value: 2000,
        median_value: 2000,
        stddev_value: 816.5,
        delta_value: 500,
        first_timestamp: "2026-01-01T00:00:01Z",
        last_timestamp: "2026-01-01T00:00:03Z",
      },
    ],
    trends: [
      {
        metric: "engine_rpm",
        direction: "increasing",
        strength: "moderate",
        slope: 1.5,
      },
    ],
    buckets: [
      {
        bucket_start: "2026-01-01T00:00:00Z",
        bucket_end: "2026-01-01T01:00:00Z",
        sample_count: 3,
      },
    ],
    gaps: { max_gap_seconds: null, gap_count: 0, expected_interval_seconds: 1 },
    run_segments: [
      {
        run_id: "46c9b21e-0c84-4d2c-8b2b-7b1c0f0a3a71",
        samples: 3,
        first_timestamp: "2026-01-01T00:00:01Z",
        last_timestamp: "2026-01-01T00:00:03Z",
        is_legacy: false,
      },
    ],
    snapshot_count: 1,
    snapshots_present: true,
    ...overrides,
  };
}

describe("VehicleAnalyticsView historical aggregations", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("renders the window summary with metric aggregates and run segments", () => {
    vi.mocked(useHistoricalAnalytics).mockReturnValue({
      data: analytics(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useHistoricalAnalytics>);

    renderWithProviders(<VehicleAnalyticsView />);

    expect(screen.getByText("Historical analytics")).toBeTruthy();
    expect(screen.getByText("Window summary")).toBeTruthy();
    expect(screen.getByText("Metric aggregates")).toBeTruthy();
    expect(screen.getByText("Run boundaries")).toBeTruthy();
    expect(screen.getByText("46c9b21e-0c84-4d2c-8b2b-7b1c0f0a3a71")).toBeTruthy();
  });

  it("never fabricates data for an empty historical window", () => {
    vi.mocked(useHistoricalAnalytics).mockReturnValue({
      data: analytics({
        total_samples: 0,
        metrics: [],
        trends: [],
        buckets: [],
        run_segments: [],
        snapshot_count: 0,
        snapshots_present: false,
        earliest_sample_at: null,
        latest_sample_at: null,
      }),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useHistoricalAnalytics>);

    renderWithProviders(<VehicleAnalyticsView />);

    expect(
      screen.getByText(/No telemetry was persisted inside this window/),
    ).toBeTruthy();
    expect(screen.getByText(/No persisted telemetry in this window/)).toBeTruthy();
  });
});
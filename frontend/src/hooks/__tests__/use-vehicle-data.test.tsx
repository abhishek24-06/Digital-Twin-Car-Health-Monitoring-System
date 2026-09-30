import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useHealthContext,
  useLatestDiagnosis,
  useTelemetryWindow,
  useVehicles,
} from "@/hooks/use-vehicle-data";
import { agentApi, healthApi, telemetryApi, vehiclesApi } from "@/services/vehicles";
import { ApiError } from "@/lib/api-error";
import { TEST_VEHICLE, createTestQueryClient } from "@/test/utils";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("vehicle data hooks", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("unwraps the vehicle list for consumers", async () => {
    vi.spyOn(vehiclesApi, "list").mockResolvedValue({
      items: [TEST_VEHICLE],
      page: 1,
      page_size: 100,
      total: 1,
    });

    const { result } = renderHook(() => useVehicles(), { wrapper });

    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(result.current.data?.[0].vin).toBe(TEST_VEHICLE.vin);
  });

  it("normalises a missing health snapshot (404) to null", async () => {
    vi.spyOn(healthApi, "latest").mockRejectedValue(
      new ApiError(404, "No health snapshot"),
    );

    const { result } = renderHook(() => useHealthContext(TEST_VEHICLE.id), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
    expect(result.current.isError).toBe(false);
  });

  it("propagates a real health failure instead of masking it as empty", async () => {
    vi.spyOn(healthApi, "latest").mockRejectedValue(
      new ApiError(503, "The service is temporarily unavailable."),
    );

    const { result } = renderHook(() => useHealthContext(TEST_VEHICLE.id), {
      wrapper,
    });

    // The hook retries once, so allow for the backoff.
    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 4000,
    });
    expect(result.current.data).toBeUndefined();
  });

  it("normalises a missing diagnosis (404) to null", async () => {
    vi.spyOn(agentApi, "latest").mockRejectedValue(
      new ApiError(404, "Diagnosis not found"),
    );

    const { result } = renderHook(() => useLatestDiagnosis(TEST_VEHICLE.id), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it("requests a trailing window computed at fetch time, not at render", async () => {
    const before = Date.now();
    const list = vi.spyOn(telemetryApi, "list").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 100,
      total: 0,
    });

    const { result } = renderHook(
      () =>
        useTelemetryWindow(TEST_VEHICLE.id, { key: "1h", minutes: 60 }, {
          page: 2,
          pageSize: 50,
        }),
      { wrapper },
    );

    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    const params = list.mock.calls[0][1];
    expect(params).toMatchObject({ page: 2, pageSize: 50 });

    const start = new Date(params!.startTime as string).getTime();
    const end = new Date(params!.endTime as string).getTime();
    expect(end - start).toBe(60 * 60_000);
    expect(end).toBeGreaterThanOrEqual(before);
    // placeholderData keeps the previous page on screen while refetching, so
    // the settled state is asserted via the fetched flag rather than isSuccess.
    await waitFor(() => expect(result.current.isFetched).toBe(true));
    expect(result.current.error).toBeNull();
  });

  it("keeps the query disabled without a vehicle id", async () => {
    const list = vi.spyOn(telemetryApi, "list");
    renderHook(
      () => useTelemetryWindow(null, { key: "1h", minutes: 60 }),
      { wrapper },
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(list).not.toHaveBeenCalled();
  });
});

describe("query cache config", () => {
  it("creates a client with retries disabled for deterministic tests", () => {
    const client = createTestQueryClient();
    expect(
      client.getDefaultOptions().queries?.retry,
    ).toBe(false);
  });
});

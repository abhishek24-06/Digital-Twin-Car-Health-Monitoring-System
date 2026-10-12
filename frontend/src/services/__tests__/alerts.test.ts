import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
  },
}));

import { alertsApi } from "@/services/alerts";

/**
 * Locks the alerts HTTP contract.
 *
 * `buildQuery` drops `undefined` values and uses single-value params, so the
 * service must never send `status=undefined`. These tests pin the exact URLs
 * and bodies the Alerts tab depends on.
 */
describe("alertsApi", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });

  afterEach(() => vi.restoreAllMocks());

  it("lists a vehicle's alerts with pagination defaults", async () => {
    getMock.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });

    await alertsApi.list("v1");

    expect(getMock).toHaveBeenCalledWith("/vehicles/v1/alerts", {
      query: { status: undefined, severity: undefined, page: 1, page_size: 20 },
    });
  });

  it("forwards status, severity, page and page size when filtering", async () => {
    getMock.mockResolvedValue({ items: [], page: 2, page_size: 50, total: 0 });

    await alertsApi.list("v1", {
      status: "acknowledged",
      severity: "critical",
      page: 2,
      pageSize: 50,
    });

    expect(getMock).toHaveBeenCalledWith("/vehicles/v1/alerts", {
      query: {
        status: "acknowledged",
        severity: "critical",
        page: 2,
        page_size: 50,
      },
    });
  });

  it("forwards the abort signal so a filter change cancels the old request", async () => {
    getMock.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });
    const controller = new AbortController();

    await alertsApi.list("v1", {}, controller.signal);

    expect(getMock).toHaveBeenCalledWith("/vehicles/v1/alerts", {
      query: { status: undefined, severity: undefined, page: 1, page_size: 20 },
      signal: controller.signal,
    });
  });

  it("fetches one alert's detail (evidence + audit history)", async () => {
    getMock.mockResolvedValue({});

    await alertsApi.get("v1", "a1");

    expect(getMock).toHaveBeenCalledWith("/vehicles/v1/alerts/a1", {});
  });

  it("acknowledges without a body when no note is supplied", async () => {
    postMock.mockResolvedValue({});

    await alertsApi.acknowledge("v1", "a1");

    expect(postMock).toHaveBeenCalledWith("/vehicles/v1/alerts/a1/acknowledge", {});
  });

  it("sends a trimmed note when resolving", async () => {
    postMock.mockResolvedValue({});

    await alertsApi.resolve("v1", "a1", "  Replaced the thermostat  ");

    expect(postMock).toHaveBeenCalledWith("/vehicles/v1/alerts/a1/resolve", {
      note: "Replaced the thermostat",
    });
  });

  it("treats a whitespace-only note as no note", async () => {
    postMock.mockResolvedValue({});

    await alertsApi.acknowledge("v1", "a1", "   ");

    expect(postMock).toHaveBeenCalledWith("/vehicles/v1/alerts/a1/acknowledge", {});
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => getMock(...args),
  },
}));

import { createWorkflowEventSource, workflowApi } from "@/services/workflow";

class FakeEventSource {
  readonly url: string;
  constructor(url: string) {
    this.url = url;
  }
}

describe("workflowApi.getState", () => {
  beforeEach(() => getMock.mockReset());
  afterEach(() => vi.unstubAllGlobals());

  it("fetches derived state scoped to one vehicle", async () => {
    getMock.mockResolvedValue({ items: [] });

    await workflowApi.getState({ vehicle_id: "v1" });

    expect(getMock).toHaveBeenCalledWith("/workflow/state", {
      query: { vehicle_id: "v1" },
    });
  });

  it("fetches derived state for all accessible vehicles without params", async () => {
    getMock.mockResolvedValue({ items: [] });

    await workflowApi.getState();

    expect(getMock).toHaveBeenCalledWith("/workflow/state", { query: undefined });
  });
});

describe("createWorkflowEventSource", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("forwards correlation_id to the proxy URL", () => {
    vi.stubGlobal("EventSource", FakeEventSource);

    const source = createWorkflowEventSource({
      correlation_id: "corr-1",
    }) as unknown as { url: string };

    expect(source.url).toContain("correlation_id=corr-1");
  });
});

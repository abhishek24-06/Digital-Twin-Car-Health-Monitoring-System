import { describe, expect, it } from "vitest";
import { VEHICLE_TABS } from "@/components/layout/nav-items";

/**
 * Decision 4 of the product spec fixes the vehicle workspace at eight tabs.
 * This pins both the set and the order so a future change has to be deliberate.
 */
describe("VEHICLE_TABS", () => {
  it("is the eight-tab vehicle workspace in the approved order", () => {
    expect(VEHICLE_TABS.map((tab) => tab.label)).toEqual([
      "Overview",
      "Live Health",
      "Simulation",
      "Analytics",
      "Telemetry",
      "AI Diagnosis",
      "History",
      "Alerts",
    ]);
  });

  it("routes each tab to its workspace sub-path", () => {
    expect(VEHICLE_TABS.map((tab) => tab.href)).toEqual([
      "",
      "/health",
      "/simulation",
      "/analytics",
      "/telemetry",
      "/diagnosis",
      "/history",
      "/alerts",
    ]);
  });
});

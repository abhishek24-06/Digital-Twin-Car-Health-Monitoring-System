import { describe, expect, it } from "vitest";
import { formatMetricValue, formatPercent } from "@/lib/format";

describe("formatMetricValue", () => {
  it("formats temperatures with one decimal", () => {
    expect(formatMetricValue(87.443, "°C")).toBe("87.4");
    // Backend unit spelling (METRIC_UNITS), e.g. alert evidence.
    expect(formatMetricValue(87.443, "C")).toBe("87.4");
  });

  it("formats rpm as a grouped integer, never with decimals", () => {
    expect(formatMetricValue(3200, "rpm")).toBe("3,200");
    expect(formatMetricValue(3200.6, "rpm")).toBe("3,201");
    // Backend unit spelling (METRIC_UNITS).
    expect(formatMetricValue(3200, "RPM")).toBe("3,200");
  });

  it("formats the remaining display units", () => {
    expect(formatMetricValue(14.23, "V")).toBe("14.2");
    expect(formatMetricValue(61.44, "%")).toBe("61.4");
    expect(formatMetricValue(88.6, "km/h")).toBe("89");
    expect(formatMetricValue(5200.2, "s")).toBe("5,200");
    expect(formatMetricValue(81234.44, "km")).toBe("81234.4");
  });

  it("renders missing values as an em dash", () => {
    expect(formatMetricValue(null, "rpm")).toBe("—");
    expect(formatMetricValue(undefined, "°C")).toBe("—");
  });
});

describe("formatPercent", () => {
  it("maps the 0..1 confidence/coverage range onto percent strings", () => {
    expect(formatPercent(0.99)).toBe("99%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(0)).toBe("0%");
  });

  it("renders missing values as an em dash", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
  });
});

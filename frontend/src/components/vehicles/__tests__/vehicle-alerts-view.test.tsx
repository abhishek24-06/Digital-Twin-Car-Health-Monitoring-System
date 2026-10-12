import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VehicleAlertsView } from "@/components/vehicles/vehicle-alerts-view";
import { alertsApi } from "@/services/alerts";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";
import type { AlertDetail, AlertItem } from "@/types/api";

const params = vi.hoisted(() => ({
  id: "22222222-2222-4222-8222-222222222222",
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: params.id }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/vehicles/1/alerts",
}));

vi.mock("@/services/alerts", () => ({
  alertsApi: {
    list: vi.fn(),
    get: vi.fn(),
    acknowledge: vi.fn(),
    resolve: vi.fn(),
  },
}));

const VEHICLE_ID = TEST_VEHICLE.id;

const OPEN_ALERT: AlertItem = {
  id: "aaaaaaaa-0000-4000-8000-000000000001",
  vehicle_id: VEHICLE_ID,
  simulation_run_id: "bbbbbbbb-0000-4000-8000-000000000001",
  rule_id: "COOLANT_TEMP_HIGH",
  category: "thermal",
  severity: "critical",
  status: "open",
  title: "Coolant temperature above safe range",
  message: "Coolant reached 108.2°C, above the 105°C limit.",
  metric: "coolant_temperature",
  observed_value: 108.2,
  threshold: 105,
  unit: "C",
  confidence: 0.9,
  provisional: false,
  occurrence_count: 3,
  first_seen_at: "2026-01-01T10:00:00Z",
  last_seen_at: "2026-01-01T10:05:00Z",
  snapshot_id: "cccccccc-0000-4000-8000-000000000001",
  acknowledged_at: null,
  acknowledged_by: null,
  acknowledge_note: null,
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
  created_at: "2026-01-01T10:05:01Z",
  updated_at: "2026-01-01T10:05:01Z",
};

const RESOLVED_ALERT: AlertItem = {
  ...OPEN_ALERT,
  id: "aaaaaaaa-0000-4000-8000-000000000002",
  rule_id: "OIL_TEMP_HIGH",
  severity: "warning",
  status: "resolved",
  title: "Oil temperature elevated",
  message: "Oil temperature stayed above its warning threshold.",
  resolved_at: "2026-01-01T11:00:00Z",
  resolved_by: null,
  resolution_note: "Condition cleared on the next evaluation.",
};

const OPEN_ALERT_DETAIL: AlertDetail = {
  ...OPEN_ALERT,
  evidence: { coolant_c: 108.2, threshold_c: 105, samples: 42 },
  events: [
    {
      id: "e0000000-0000-4000-8000-000000000001",
      event_type: "created",
      from_status: null,
      to_status: "open",
      actor_user_id: null,
      note: null,
      created_at: "2026-01-01T10:05:01Z",
    },
    {
      id: "e0000000-0000-4000-8000-000000000002",
      event_type: "acknowledged",
      from_status: "open",
      to_status: "acknowledged",
      actor_user_id: "99999999-9999-4999-8999-999999999999",
      note: "Booking a service slot",
      created_at: "2026-01-01T10:10:00Z",
    },
  ],
};

function page(items: AlertItem[], total = items.length) {
  return { items, page: 1, page_size: 20, total };
}

describe("VehicleAlertsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    params.id = TEST_VEHICLE.id;
    vi.mocked(alertsApi.list).mockResolvedValue(page([]));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders persisted alerts with their severity, status and rule", async () => {
    vi.mocked(alertsApi.list).mockResolvedValue(page([OPEN_ALERT]));
    renderWithProviders(<VehicleAlertsView />);

    expect(
      await screen.findByText("Coolant temperature above safe range"),
    ).toBeTruthy();
    const row = within(screen.getByRole("list")).getByText("Coolant temperature above safe range");
    expect(within(row.closest("li")!).getByText("Critical")).toBeTruthy();
    expect(screen.getByText("open")).toBeTruthy();
    expect(screen.getByText("COOLANT_TEMP_HIGH")).toBeTruthy();
    expect(screen.getByText("×3")).toBeTruthy();
  });

  it("shows the honest empty state when there are no alerts", async () => {
    renderWithProviders(<VehicleAlertsView />);

    expect(await screen.findByText("No alerts")).toBeTruthy();
    expect(
      screen.getByText(/Alerts appear when a current-session health evaluation/),
    ).toBeTruthy();
  });

  it("asks the backend for an alert's detail and shows evidence and audit history", async () => {
    const user = userEvent.setup();
    vi.mocked(alertsApi.list).mockResolvedValue(page([OPEN_ALERT]));
    vi.mocked(alertsApi.get).mockResolvedValue(OPEN_ALERT_DETAIL);

    renderWithProviders(<VehicleAlertsView />);

    await user.click(
      await screen.findByRole("button", {
        name: "Coolant temperature above safe range",
      }),
    );

    expect(await screen.findByText("Audit history")).toBeTruthy();
    expect(screen.getByText("Evidence")).toBeTruthy();
    expect(screen.getByText("coolant_c")).toBeTruthy();
    expect(screen.getByText("108.2")).toBeTruthy();
    // The creation event is attributed to the system, not a person.
    expect(screen.getByText("System")).toBeTruthy();
    // "Acknowledged" is both a status-filter option and the audit event label.
    expect(screen.getAllByText("Acknowledged").length).toBeGreaterThan(1);
    expect(screen.getByText(/Booking a service slot/)).toBeTruthy();

    await waitFor(() =>
      expect(alertsApi.get).toHaveBeenCalledWith(
        VEHICLE_ID,
        OPEN_ALERT.id,
        expect.anything(),
      ),
    );
  });

  it("acknowledges an alert (recording the action) without opening the dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(alertsApi.list).mockResolvedValue(page([OPEN_ALERT]));
    vi.mocked(alertsApi.acknowledge).mockResolvedValue({
      ...OPEN_ALERT_DETAIL,
      status: "acknowledged",
      acknowledged_at: "2026-01-01T10:10:00Z",
    });

    renderWithProviders(<VehicleAlertsView />);

    await user.click(
      await screen.findByRole("button", { name: "Acknowledge" }),
    );

    await waitFor(() =>
      expect(alertsApi.acknowledge).toHaveBeenCalledWith(
        VEHICLE_ID,
        OPEN_ALERT.id,
        undefined,
      ),
    );
  });

  it("offers no acknowledge or resolve action on a resolved alert", async () => {
    vi.mocked(alertsApi.list).mockResolvedValue(page([RESOLVED_ALERT]));
    renderWithProviders(<VehicleAlertsView />);

    expect(await screen.findByText("Oil temperature elevated")).toBeTruthy();
    expect(screen.getByText("resolved")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
    // The record is still inspectable.
    expect(screen.getByRole("button", { name: /Details/ })).toBeTruthy();
  });

  it("passes the selected status filter to the backend request", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VehicleAlertsView />);

    const group = await screen.findByRole("group", {
      name: "Filter alerts by status",
    });
    await user.click(within(group).getByRole("button", { name: "Open" }));

    await waitFor(() =>
      expect(alertsApi.list).toHaveBeenCalledWith(
        VEHICLE_ID,
        expect.objectContaining({ status: "open", page: 1 }),
        expect.anything(),
      ),
    );
  });

  it("never shows one vehicle's alerts while another vehicle's are loading", async () => {
    vi.mocked(alertsApi.list).mockImplementation((vehicleId) =>
      Promise.resolve(vehicleId === VEHICLE_ID ? page([OPEN_ALERT]) : page([])),
    );

    const { rerender } = renderWithProviders(<VehicleAlertsView />);
    expect(
      await screen.findByText("Coolant temperature above safe range"),
    ).toBeTruthy();

    // Navigate to a different vehicle; the placeholder must be scoped, so the
    // previous vehicle's alert cannot leak into the new vehicle's view.
    params.id = "dddddddd-0000-4000-8000-000000000002";
    rerender(<VehicleAlertsView />);

    await waitFor(() =>
      expect(
        screen.queryByText("Coolant temperature above safe range"),
      ).toBeNull(),
    );
    expect(await screen.findByText("No alerts")).toBeTruthy();
  });
});

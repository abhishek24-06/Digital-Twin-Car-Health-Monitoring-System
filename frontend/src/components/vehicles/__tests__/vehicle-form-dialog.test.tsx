import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VehicleFormDialog } from "@/components/vehicles/vehicle-form-dialog";
import { renderWithProviders, TEST_VEHICLE } from "@/test/utils";

describe("VehicleFormDialog", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("enforces the backend's VIN and year bounds before submitting", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(
      <VehicleFormDialog open onOpenChange={() => {}} onSubmit={onSubmit} />,
    );

    await user.click(screen.getByRole("button", { name: /add vehicle|save/i }));

    expect(await screen.findByText(/enter the manufacturer/i)).toBeTruthy();
    expect(screen.getByText(/enter the model\./i)).toBeTruthy();
    expect(screen.getByText(/enter the model year/i)).toBeTruthy();
    expect(screen.getByText(/VIN must be 5–50 characters/i)).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a year outside 1900–2100", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(
      <VehicleFormDialog open onOpenChange={() => {}} onSubmit={onSubmit} />,
    );

    await user.type(screen.getByLabelText(/^vin/i), "1HGCM82633A004352");
    await user.type(screen.getByLabelText(/^make/i), "Honda");
    await user.type(screen.getByLabelText(/^model/i), "Civic");
    await user.type(screen.getByLabelText(/year/i), "1899");
    await user.click(screen.getByRole("button", { name: /add vehicle|save/i }));

    expect(
      await screen.findByText(/year must be between 1900 and 2100/i),
    ).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("upper-cases the VIN and omits nothing on create", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <VehicleFormDialog open onOpenChange={() => {}} onSubmit={onSubmit} />,
    );

    await user.type(screen.getByLabelText(/^vin/i), "1hgcm82633a004352");
    await user.type(screen.getByLabelText(/^make/i), "Honda");
    await user.type(screen.getByLabelText(/^model/i), "Civic");
    await user.type(screen.getByLabelText(/year/i), "2019");
    await user.type(screen.getByLabelText(/engine/i), "1.5L Turbo");
    await user.click(screen.getByRole("button", { name: /add vehicle|save/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      vin: "1HGCM82633A004352",
      make: "Honda",
      model: "Civic",
      year: 2019,
      engine_type: "1.5L Turbo",
    });
  });

  it("locks the VIN in edit mode, because the backend treats it as immutable", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <VehicleFormDialog
        open
        onOpenChange={() => {}}
        vehicle={TEST_VEHICLE}
        onSubmit={onSubmit}
      />,
    );

    const vin = screen.getByLabelText(/^vin/i) as HTMLInputElement;
    expect(vin.value).toBe(TEST_VEHICLE.vin);
    expect(vin.disabled).toBe(true);
    expect(screen.getByText(/immutable after registration/i)).toBeTruthy();
    expect(screen.getByLabelText(/^make/i)).toHaveValue("Honda");
  });

  it("resets to blank when reopened for a different vehicle", async () => {
    const { rerender } = renderWithProviders(
      <VehicleFormDialog
        open
        onOpenChange={() => {}}
        vehicle={TEST_VEHICLE}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/^model/i)).toHaveValue("Civic");

    rerender(
      <VehicleFormDialog open onOpenChange={() => {}} onSubmit={vi.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByLabelText(/^model/i)).toHaveValue(""),
    );
    expect(screen.getByLabelText(/^model/i)).not.toBeDisabled();
  });
});

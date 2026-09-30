"use client";

import * as React from "react";
import { Save } from "lucide-react";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorState } from "@/components/states/feedback";
import { toApiError } from "@/lib/api-error";
import type { VehicleCreate, VehicleResponse } from "@/types/api";

/** Backend constraints (see `app/schemas/vehicle.py`). */
const VIN_MIN = 5;
const VIN_MAX = 50;
const YEAR_MIN = 1900;
const YEAR_MAX = 2100;

export interface VehicleFormValues extends VehicleCreate {
  vin: string;
}

interface VehicleFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Present for edit mode; the VIN is immutable once created. */
  vehicle?: VehicleResponse | null;
  onSubmit: (values: VehicleFormValues) => Promise<unknown>;
}

export function VehicleFormDialog({
  open,
  onOpenChange,
  vehicle,
  onSubmit,
}: VehicleFormDialogProps) {
  // Keyed by "open + vehicle" so opening the dialog for a different vehicle
  // remounts the form with fresh values instead of syncing state mid-render.
  const seedKey = `${open}-${vehicle?.id ?? "new"}`;
  if (!open) return null;

  return (
    <VehicleForm
      key={seedKey}
      vehicle={vehicle ?? null}
      onOpenChange={onOpenChange}
      onSubmit={onSubmit}
    />
  );
}

function VehicleForm({
  vehicle,
  onOpenChange,
  onSubmit,
}: {
  vehicle: VehicleResponse | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: VehicleFormValues) => Promise<unknown>;
}) {
  const editing = Boolean(vehicle);
  const [make, setMake] = React.useState(vehicle?.make ?? "");
  const [model, setModel] = React.useState(vehicle?.model ?? "");
  const [year, setYear] = React.useState(String(vehicle?.year ?? ""));
  const [engineType, setEngineType] = React.useState(vehicle?.engine_type ?? "");
  const [vin, setVin] = React.useState(vehicle?.vin ?? "");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<unknown>(null);
  const [saving, setSaving] = React.useState(false);

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!editing) {
      const value = vin.trim().toUpperCase();
      if (value.length < VIN_MIN || value.length > VIN_MAX)
        next.vin = `VIN must be ${VIN_MIN}–${VIN_MAX} characters.`;
    }
    if (!make.trim()) next.make = "Enter the manufacturer.";
    if (!model.trim()) next.model = "Enter the model.";

    const parsedYear = Number(year);
    if (!year.trim()) next.year = "Enter the model year.";
    else if (!Number.isInteger(parsedYear) || parsedYear < YEAR_MIN || parsedYear > YEAR_MAX)
      next.year = `Year must be between ${YEAR_MIN} and ${YEAR_MAX}.`;

    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    setError(null);
    if (!validate()) return;

    setSaving(true);
    try {
      const values: VehicleFormValues = {
        make: make.trim(),
        model: model.trim(),
        year: Number(year),
        engine_type: engineType.trim() ? engineType.trim() : null,
        vin: editing ? (vehicle?.vin as string) : vin.trim().toUpperCase(),
      };
      await onSubmit(values);
      onOpenChange(false);
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      if (Object.keys(apiError.fieldErrors).length > 0) {
        setErrors(
          Object.fromEntries(
            Object.entries(apiError.fieldErrors).map(([key, list]) => [key, list[0] ?? ""]),
          ),
        );
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit} noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? "Edit vehicle" : "Add a vehicle"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "The VIN is fixed once a vehicle is registered; it is the key the telemetry pipeline uses."
                : "Use the VIN from the driver's door jamb or dashboard. It is stored as entered (upper-cased) and cannot be changed later."}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-4">
            {error ? <ErrorState error={error} compact /> : null}

            <Field
              label="VIN"
              htmlFor="vin"
              required={!editing}
              hint={
                editing
                  ? "Immutable after registration."
                  : `${VIN_MIN}–${VIN_MAX} characters, letters and digits.`
              }
              error={errors.vin}
            >
              <Input
                id="vin"
                value={vin}
                disabled={editing}
                maxLength={VIN_MAX}
                autoComplete="off"
                spellCheck={false}
                className="font-mono uppercase"
                placeholder="1HGCM82633A004352"
                invalid={Boolean(errors.vin)}
                onChange={(event) => setVin(event.target.value)}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Make" htmlFor="make" required error={errors.make}>
                <Input
                  id="make"
                  value={make}
                  maxLength={80}
                  invalid={Boolean(errors.make)}
                  onChange={(event) => setMake(event.target.value)}
                  placeholder="Honda"
                />
              </Field>
              <Field label="Model" htmlFor="model" required error={errors.model}>
                <Input
                  id="model"
                  value={model}
                  maxLength={80}
                  invalid={Boolean(errors.model)}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="Civic"
                />
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Year"
                htmlFor="year"
                required
                hint={`${YEAR_MIN}–${YEAR_MAX}`}
                error={errors.year}
              >
                <Input
                  id="year"
                  type="number"
                  inputMode="numeric"
                  min={YEAR_MIN}
                  max={YEAR_MAX}
                  value={year}
                  invalid={Boolean(errors.year)}
                  onChange={(event) => setYear(event.target.value)}
                  placeholder="2019"
                />
              </Field>
              <Field
                label="Engine"
                htmlFor="engine_type"
                hint="Optional, e.g. 1.5L Turbo I4."
                error={errors.engine_type}
              >
                <Input
                  id="engine_type"
                  value={engineType}
                  maxLength={80}
                  onChange={(event) => setEngineType(event.target.value)}
                  placeholder="1.5L Turbo I4"
                />
              </Field>
            </div>
          </DialogBody>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              <Save aria-hidden />
              {editing ? "Save changes" : "Add vehicle"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

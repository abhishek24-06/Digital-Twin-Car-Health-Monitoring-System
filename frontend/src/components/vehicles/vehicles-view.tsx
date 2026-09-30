"use client";

import * as React from "react";
import Link from "next/link";
import {
  Car,
  ChevronRight,
  Pencil,
  PlusCircle,
  Radio,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { VehicleFormDialog, type VehicleFormValues } from "@/components/vehicles/vehicle-form-dialog";
import { useVehicles } from "@/hooks/use-vehicle-data";
import { useCreateVehicle, useDeleteVehicle, useUpdateVehicle } from "@/hooks/use-mutations";
import { useVehicleSelection } from "@/stores/vehicle-selection";
import { useSessionStore } from "@/lib/session-store";
import { cn } from "@/lib/utils";
import type { VehicleResponse } from "@/types/api";

/** Vehicle registry: create, edit and delete, with delete confirmation. */
export function VehiclesView() {
  const { data: vehicles, isPending, isError, error, refetch } = useVehicles();
  const isAdmin = useSessionStore((state) => state.user?.role === "admin");
  const selectedId = useVehicleSelection((state) => state.selectedVehicleId);
  const selectVehicle = useVehicleSelection((state) => state.select);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<VehicleResponse | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<VehicleResponse | null>(null);

  const createVehicle = useCreateVehicle();
  // Bound to whichever vehicle the dialog is editing; the id is set when the
  // dialog opens, so the mutation always targets the right row.
  const updateVehicle = useUpdateVehicle(editing?.id ?? "");
  const deleteVehicle = useDeleteVehicle();

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (vehicle: VehicleResponse) => {
    setEditing(vehicle);
    setFormOpen(true);
  };

  const submitForm = async (values: VehicleFormValues) => {
    if (editing) {
      // VIN is immutable, so it is deliberately not part of the update payload.
      await updateVehicle.mutateAsync({
        make: values.make,
        model: values.model,
        year: values.year,
        engine_type: values.engine_type,
      });
      return;
    }
    const created = await createVehicle.mutateAsync(values);
    if (created?.id) selectVehicle(created.id);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const removingId = pendingDelete.id;
    await deleteVehicle.mutateAsync(removingId).catch(() => undefined);
    if (selectedId === removingId) selectVehicle(null);
    setPendingDelete(null);
  };

  const isEmpty = !isPending && !isError && (vehicles?.length ?? 0) === 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="My vehicles"
        description="Every vehicle you register is monitored independently. Telemetry is matched by VIN."
        actions={
          <Button size="sm" onClick={openCreate}>
            <PlusCircle aria-hidden />
            Add vehicle
          </Button>
        }
      />

      {isAdmin ? (
        <InlineAlert tone="info">
          You are signed in as an administrator, so the list includes vehicles owned by
          other accounts (the backend enforces this for the admin role).
        </InlineAlert>
      ) : null}

      {isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : isEmpty ? (
        <EmptyState
          icon={<Car className="size-5" aria-hidden />}
          title="No vehicles registered"
          description="Register your first vehicle with its VIN to begin collecting telemetry and health analysis."
          action={
            <Button size="sm" onClick={openCreate}>
              <PlusCircle aria-hidden />
              Add a vehicle
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {vehicles?.map((vehicle) => (
            <VehicleCard
              key={vehicle.id}
              vehicle={vehicle}
              isActive={vehicle.id === selectedId}
              onSelect={() => selectVehicle(vehicle.id)}
              onEdit={() => openEdit(vehicle)}
              onDelete={() => setPendingDelete(vehicle)}
            />
          ))}
        </div>
      )}

      <VehicleFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        vehicle={editing}
        onSubmit={submitForm}
      />

      <Dialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this vehicle?</DialogTitle>
            <DialogDescription>
              {pendingDelete
                ? `${pendingDelete.make} ${pendingDelete.model} (${pendingDelete.vin}) and all of its telemetry, health snapshots and diagnoses will be removed. This cannot be undone.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {deleteVehicle.isError ? (
              <ErrorState error={deleteVehicle.error} compact />
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setPendingDelete(null)}
              disabled={deleteVehicle.isPending}
            >
              Keep vehicle
            </Button>
            <Button
              variant="danger"
              loading={deleteVehicle.isPending}
              onClick={confirmDelete}
            >
              <Trash2 aria-hidden />
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function VehicleCard({
  vehicle,
  isActive,
  onSelect,
  onEdit,
  onDelete,
}: {
  vehicle: VehicleResponse;
  isActive: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <Card
      className={cn(
        "flex flex-col gap-3 p-4 transition-colors",
        isActive ? "border-signal-500/50" : "hover:border-line-strong",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink">
            {vehicle.make} {vehicle.model}
          </h2>
          <p className="tabular mt-0.5 text-xs text-ink-subtle">
            {vehicle.year} · {vehicle.engine_type ?? "engine unspecified"}
          </p>
        </div>
        {isActive ? (
          <Badge tone="accent" size="sm">
            active
          </Badge>
        ) : null}
      </div>

      <dl className="space-y-1 text-xs">
        <div className="flex items-center gap-2">
          <dt className="text-ink-subtle">VIN</dt>
          <dd className="truncate font-mono text-ink-muted">{vehicle.vin}</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-ink-subtle">Status</dt>
          <dd className="text-ink-muted">{vehicle.status}</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-ink-subtle">Source</dt>
          <dd className="text-ink-muted">{vehicle.source_type}</dd>
        </div>
      </dl>

      {vehicle.simulation_enabled ? (
        <p className="inline-flex items-center gap-1.5 text-[0.65rem] text-[color:var(--color-attention)]">
          <Radio className="size-3" aria-hidden />
          Simulation enabled on the backend
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button asChild size="sm" variant="outline" onClick={onSelect}>
          <Link href={`/vehicles/${vehicle.id}`}>
            Open
            <ChevronRight aria-hidden />
          </Link>
        </Button>
        <Button size="iconSm" variant="ghost" onClick={onEdit} aria-label={`Edit ${vehicle.make} ${vehicle.model}`}>
          <Pencil aria-hidden />
        </Button>
        <Button
          size="iconSm"
          variant="ghost"
          onClick={onDelete}
          aria-label={`Delete ${vehicle.make} ${vehicle.model}`}
          className="text-[color:var(--color-critical)] hover:bg-surface-2"
        >
          <Trash2 aria-hidden />
        </Button>
      </div>
    </Card>
  );
}

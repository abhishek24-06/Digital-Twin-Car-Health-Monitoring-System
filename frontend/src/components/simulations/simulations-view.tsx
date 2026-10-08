"use client";

import * as React from "react";
import Link from "next/link";
import { CirclePlay, Play, RotateCw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { SelectMenu, type SelectOption } from "@/components/ui/select-menu";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { useSimulations } from "@/hooks/use-simulations";
import { useVehicles } from "@/hooks/use-vehicle-data";
import {
  useRestartSimulation,
  useStartSimulation,
  useStopSimulation,
} from "@/hooks/use-mutations";
import { ApiError, toApiError } from "@/lib/api-error";
import { formatRelative } from "@/lib/format";
import type {
  SimulationScenario,
  SimulationState,
  SimulationStatusResponse,
  VehicleResponse,
} from "@/types/api";

const SCENARIO_OPTIONS: ReadonlyArray<SelectOption<SimulationScenario>> = [
  { value: "normal", label: "Normal", description: "Steady, realistic driving conditions" },
  {
    value: "high_temperature",
    label: "High temperature",
    description: "Coolant and oil temperatures driven up",
  },
  { value: "low_battery", label: "Low battery", description: "Battery voltage depressed" },
  {
    value: "high_engine_load",
    label: "High engine load",
    description: "Sustained heavy load and RPM",
  },
];

const STATUS_TONE: Record<
  SimulationState,
  "neutral" | "accent" | "healthy" | "attention" | "critical" | "unknown"
> = {
  stopped: "neutral",
  starting: "attention",
  running: "healthy",
  stopping: "attention",
  degraded: "attention",
  error: "critical",
};

/** User-facing copy for a failed simulation action. */
export function simulationErrorMessage(error: ApiError | null): string {
  if (!error) return "";
  switch (error.status) {
    case 0:
      return "Cannot reach the backend. Check that it is running.";
    case 401:
      return "Your session expired — sign in again.";
    case 403:
      return "You do not have access to this vehicle.";
    case 404:
      return "Vehicle not found, or you do not have access.";
    case 409:
      return "A simulation is already running for this vehicle. Use Restart to apply changes.";
    case 502:
      return error.message
        ? error.message
        : "The simulator could not be started on the backend.";
    default:
      return error.message ? `Request failed: ${error.message}` : "The request failed. Try again.";
  }
}

export function SimulationsView() {
  const { data: vehicles, isPending, isError, error, refetch } = useVehicles();
  const {
    data: statuses,
    isError: statusesLoadFailed,
    error: statusesError,
  } = useSimulations();

  const statusMap = React.useMemo(
    () => new Map(statuses?.map((status) => [status.vehicle_id, status]) ?? []),
    [statuses],
  );

  const isEmpty = !isPending && !isError && (vehicles?.length ?? 0) === 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Simulation control"
        description="Run the telemetry simulator for each of your vehicles to produce a steady, realistic data feed. Statuses refresh automatically."
      />

      {statusesLoadFailed ? (
        <InlineAlert tone="attention" title="Could not refresh simulation statuses">
          {simulationErrorMessage(toApiError(statusesError))} Showing the last known state.
        </InlineAlert>
      ) : null}

      {isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-56 rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : isEmpty ? (
        <EmptyState
          icon={<CirclePlay className="size-5" aria-hidden />}
          title="No vehicles registered"
          description="Simulation Control starts one simulator per registered vehicle. Register a vehicle first, then come back here to drive its telemetry feed."
          action={
            <Button asChild size="sm">
              <Link href="/vehicles">Register a vehicle</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {vehicles?.map((vehicle) => (
            <SimulationCard
              key={vehicle.id}
              vehicle={vehicle}
              status={statusMap.get(vehicle.id) ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SimulationCard({
  vehicle,
  status,
}: {
  vehicle: VehicleResponse;
  status: SimulationStatusResponse | null;
}) {
  const name = `${vehicle.make} ${vehicle.model}`;
  const detail = `${vehicle.year}${vehicle.engine_type ? ` · ${vehicle.engine_type}` : ""}`;

  // Draft scenario + interval, seeded from the live status. Once the user edits
  // a control, external poll updates no longer overwrite their selection.
  const [touched, setTouched] = React.useState(false);
  const [scenario, setScenario] = React.useState<SimulationScenario>("normal");
  const [interval, setInterval] = React.useState(1);
  const [actionError, setActionError] = React.useState<ApiError | null>(null);

  const effectiveScenario = touched ? scenario : (status?.scenario ?? "normal");
  const effectiveInterval = touched ? interval : (status?.interval_seconds ?? 1);

  const startSim = useStartSimulation(vehicle.id);
  const restartSim = useRestartSimulation(vehicle.id);
  const stopSim = useStopSimulation(vehicle.id);

  const state = status?.status ?? "stopped";
  const isBusy = state === "starting" || state === "stopping";
  const canStart = state === "stopped" || state === "error";
  const canStop =
    state === "running" || state === "starting" || state === "stopping" || state === "degraded";
  const activeMutation =
    startSim.isPending || restartSim.isPending || stopSim.isPending;

  const run = async (mutation: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await mutation();
    } catch (caught) {
      setActionError(toApiError(caught));
    }
  };

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink">{name}</h2>
          <p className="mt-0.5 text-xs text-ink-subtle">{detail}</p>
        </div>
        <Badge tone={STATUS_TONE[state]} size="sm">
          {state}
        </Badge>
      </div>

      <dl className="space-y-1 text-xs">
        <div className="flex items-center gap-2">
          <dt className="text-ink-subtle">Started</dt>
          <dd className="text-ink-muted">
            {status?.started_at ? formatRelative(status.started_at) : "—"}
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-ink-subtle">Last telemetry</dt>
          <dd className="text-ink-muted">
            {status?.last_telemetry_at ? formatRelative(status.last_telemetry_at) : "—"}
          </dd>
        </div>
      </dl>

      {state === "error" && status?.error ? (
        <InlineAlert tone="critical" title="Simulator failed">
          {status.error}
        </InlineAlert>
      ) : null}

      {state === "degraded" && status?.error ? (
        <InlineAlert tone="attention" title="Running, but the telemetry feed is degraded">
          {status.error}
        </InlineAlert>
      ) : null}

      <div className="grid grid-cols-2 gap-3 border-t border-line pt-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ink-muted">Scenario</span>
          <SelectMenu
            value={effectiveScenario}
            options={SCENARIO_OPTIONS}
            onChange={(value) => {
              setScenario(value);
              setTouched(true);
            }}
            label={`Scenario for ${name}`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ink-muted">
            Interval (seconds)
          </span>
          <Input
            type="number"
            inputMode="decimal"
            min={0.1}
            max={60}
            step={0.1}
            value={effectiveInterval}
            disabled={isBusy || activeMutation}
            aria-label={`Publish interval for ${name}`}
            onChange={(event) => {
              const parsed = Number(event.target.value);
              if (Number.isFinite(parsed)) {
                setInterval(parsed);
                setTouched(true);
              }
            }}
          />
        </label>
      </div>

      {actionError ? (
        <InlineAlert tone="attention">{simulationErrorMessage(actionError)}</InlineAlert>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <Button
          size="sm"
          variant="primary"
          loading={startSim.isPending}
          disabled={!canStart || isBusy || activeMutation}
          onClick={() =>
            run(() =>
              startSim.mutateAsync({
                scenario: effectiveScenario,
                interval_seconds: effectiveInterval,
              }),
            )
          }
        >
          <Play aria-hidden />
          Start
        </Button>
        <Button
          size="sm"
          variant="outline"
          loading={restartSim.isPending}
          disabled={isBusy || activeMutation}
          onClick={() =>
            run(() =>
              restartSim.mutateAsync({
                scenario: effectiveScenario,
                interval_seconds: effectiveInterval,
              }),
            )
          }
        >
          <RotateCw aria-hidden />
          Restart
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={stopSim.isPending}
          disabled={!canStop || activeMutation}
          onClick={() => run(() => stopSim.mutateAsync())}
          className="text-[color:var(--color-critical)] hover:bg-surface-2"
        >
          <Square aria-hidden />
          Stop
        </Button>
      </div>
    </Card>
  );
}
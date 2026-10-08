"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { TelemetryExplorer } from "@/components/telemetry/telemetry-explorer";
import { LiveTelemetryFeed } from "@/components/telemetry/live-telemetry-feed";

/** Telemetry page: live stream feed plus the explorer for historical windows. */
export function VehicleTelemetryView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  return (
    <div className="space-y-4">
      <LiveTelemetryFeed vehicleId={vehicleId} />
      <TelemetryExplorer vehicleId={vehicleId} />
    </div>
  );
}

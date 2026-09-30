"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { TelemetryExplorer } from "@/components/telemetry/telemetry-explorer";

/** Telemetry page: the explorer plus, for operators, manual sample entry. */
export function VehicleTelemetryView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  return <TelemetryExplorer vehicleId={vehicleId} />;
}

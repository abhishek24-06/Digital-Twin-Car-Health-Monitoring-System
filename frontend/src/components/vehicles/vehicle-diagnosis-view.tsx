"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { DiagnosisPanel } from "@/components/diagnosis/diagnosis-panel";
import { useAskAgent } from "@/hooks/use-mutations";
import { useLatestDiagnosis } from "@/hooks/use-vehicle-data";

/** Diagnosis page: ask the agent and read the latest grounded interpretation. */
export function VehicleDiagnosisView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const latest = useLatestDiagnosis(vehicleId);
  const ask = useAskAgent(vehicleId);

  // A successful question replaces the panel immediately; failures keep the
  // previous diagnosis on screen with the error beside it.
  const diagnosis = ask.data ?? latest.data ?? null;
  const askError = ask.isError
    ? ask.error
    : latest.isError
      ? latest.error
      : null;

  return (
    <DiagnosisPanel
      diagnosis={diagnosis}
      isAsking={ask.isPending}
      askError={askError}
      onAsk={(question) => ask.mutate(question)}
      suggestedQuestion={
        diagnosis
          ? "What should I check first based on the latest findings?"
          : "Explain the current health of this vehicle and what I should watch."
      }
    />
  );
}

import { describe, expect, it } from "vitest";
import { PIPELINES, deriveStageStates } from "@/components/workflow/pipelines";
import type { VehicleTelemetryState, WorkflowEventResponse } from "@/types/api";

function event(overrides: Partial<WorkflowEventResponse> = {}): WorkflowEventResponse {
  return {
    event_id: "e1",
    timestamp: "2026-01-01T00:00:00Z",
    workflow: "telemetry",
    stage: "telemetry_persisted",
    status: "success",
    message: "persisted",
    vehicle_id: "v1",
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

function derivedState(stages: VehicleTelemetryState["stages"]): VehicleTelemetryState {
  return {
    vehicle_id: "v1",
    simulation_status: "running",
    stages,
    last_telemetry_at: null,
    messages_received: 0,
    snapshot_at: null,
    degraded_reason: null,
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("PIPELINES registry", () => {
  it("registers every contextual pipeline with stages", () => {
    const ids = ["telemetry", "rag_ingestion", "rag_query", "health", "agent"] as const;
    for (const id of ids) {
      expect(PIPELINES[id].stages.length).toBeGreaterThan(0);
      expect(PIPELINES[id].title.length).toBeGreaterThan(0);
    }
  });

  it("never labels the parser stage as having 'processed' a message", () => {
    for (const stage of PIPELINES.telemetry.stages) {
      expect(stage.label.toLowerCase()).not.toContain("processed");
    }
  });
});

describe("deriveStageStates", () => {
  it("marks every stage waiting when there is no signal", () => {
    const states = deriveStageStates([], PIPELINES.telemetry.stages, {
      workflow: "telemetry",
    });
    expect(states).toHaveLength(PIPELINES.telemetry.stages.length);
    expect(states.every((state) => state.status === "waiting")).toBe(true);
    expect(states.every((state) => state.observation === "none-yet")).toBe(true);
  });

  it("maps an observed telemetry_persisted success onto its stage", () => {
    const states = deriveStageStates(
      [
        event({
          stage: "telemetry_persisted",
          status: "success",
        }),
      ],
      PIPELINES.telemetry.stages,
      { workflow: "telemetry" },
    );
    const postgres = states.find((state) => state.stage === "postgres");
    expect(postgres?.status).toBe("success");
    expect(postgres?.observation).toBe("observed");
    expect(postgres?.lastEvent?.stage).toBe("telemetry_persisted");
  });

  it("ignores events from another workflow", () => {
    const states = deriveStageStates(
      [event({ workflow: "rag_query", stage: "query_received" })],
      PIPELINES.telemetry.stages,
      { workflow: "telemetry" },
    );
    expect(states.every((state) => state.status === "waiting")).toBe(true);
  });

  it("lets a derived degraded broker state override with the flow detail", () => {
    const states = deriveStageStates([], PIPELINES.telemetry.stages, {
      workflow: "telemetry",
      derivedState: derivedState([
        {
          stage: "mqtt_broker",
          status: "degraded",
          observation: "derived",
          at: null,
          detail: "No recent telemetry flow observed",
        },
      ]),
    });
    const broker = states.find((state) => state.stage === "mqtt_broker");
    expect(broker?.status).toBe("degraded");
    expect(broker?.observation).toBe("derived");
    expect(broker?.detail).toContain("No recent telemetry flow observed");
  });

  it("derives the parser stage from a healthy flow without per-message telemetry", () => {
    const states = deriveStageStates([], PIPELINES.telemetry.stages, {
      workflow: "telemetry",
      derivedState: derivedState([
        {
          stage: "parser",
          status: "success",
          observation: "derived",
          at: null,
          detail: "Receiving valid telemetry",
        },
      ]),
    });
    const parser = states.find((state) => state.stage === "parser");
    expect(parser?.status).toBe("success");
    expect(parser?.detail).toBe("Receiving valid telemetry");
  });

  it("does not fall back to a stale event for a stage the derived snapshot omits", () => {
    // The backend intentionally omits a stage when it has no real signal. An
    // older observed "success" event must never resurrect that stage as if it
    // were current -- that is how stale states survived a genuine recovery.
    const states = deriveStageStates(
      [event({ stage: "telemetry_persisted", status: "success" })],
      PIPELINES.telemetry.stages,
      {
        workflow: "telemetry",
        derivedState: derivedState([
          {
            stage: "mqtt_subscriber",
            status: "success",
            observation: "derived",
            at: null,
            detail: "Subscriber running",
          },
        ]),
      },
    );
    const postgres = states.find((state) => state.stage === "postgres");
    expect(postgres?.status).toBe("waiting");
    expect(postgres?.observation).toBe("none-yet");
    expect(postgres?.lastEvent).toBeNull();
  });

  it("prefers the derived stage over a newer-looking observed event", () => {
    const states = deriveStageStates(
      [
        event({
          stage: "telemetry_persisted",
          status: "success",
          timestamp: "2026-01-02T00:00:00Z",
        }),
      ],
      PIPELINES.telemetry.stages,
      {
        workflow: "telemetry",
        derivedState: derivedState([
          {
            stage: "postgres",
            status: "degraded",
            observation: "derived",
            at: "2026-01-01T00:00:00Z",
            detail: "Newest telemetry is stale",
          },
        ]),
      },
    );
    const postgres = states.find((state) => state.stage === "postgres");
    expect(postgres?.status).toBe("degraded");
    expect(postgres?.observation).toBe("derived");
    expect(postgres?.detail).toBe("Newest telemetry is stale");
  });
});

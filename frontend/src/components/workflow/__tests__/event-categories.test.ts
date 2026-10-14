import { describe, expect, it } from "vitest";
import {
  filterEventsByTab,
  TAB_WORKFLOW,
  tabStages,
  WORKFLOW_TABS,
  type WorkflowTab,
} from "@/components/workflow/event-categories";
import type {
  WorkflowEventResponse,
  WorkflowType,
  WorkflowStage,
} from "@/types/api";

function event(
  workflow: WorkflowType,
  stage: WorkflowStage,
  overrides: Partial<WorkflowEventResponse> = {},
): WorkflowEventResponse {
  return {
    event_id: `${workflow}-${stage}`,
    timestamp: new Date().toISOString(),
    workflow,
    stage,
    status: "success",
    message: `${workflow} ${stage}`,
    vehicle_id: null,
    document_id: null,
    correlation_id: null,
    duration_ms: null,
    metadata: {},
    ...overrides,
  };
}

function phases(events: WorkflowEventResponse[], tab: WorkflowTab): string[] {
  return filterEventsByTab(events, tab).map((e) => e.stage);
}

describe("workflow event categories", () => {
  it("maps every non-overview tab to a canonical backend workflow", () => {
    expect(TAB_WORKFLOW.overview).toBeNull();
    for (const tab of WORKFLOW_TABS) {
      if (tab === "overview") continue;
      expect(TAB_WORKFLOW[tab]).toBeTypeOf("string");
    }
    // Tab ids are the hyphenated form of their workflow value.
    expect(TAB_WORKFLOW["rag-ingestion"]).toBe("rag_ingestion");
    expect(TAB_WORKFLOW["rag-query"]).toBe("rag_query");
  });

  it("matches every event under Overview, including unknown stages", () => {
    const events = [
      event("telemetry", "telemetry_persisted"),
      event("health", "health_snapshot_created"),
      event("system", "subscriber_started"),
      event("telemetry", "brand_new_stage" as WorkflowStage),
    ];
    expect(filterEventsByTab(events, "overview")).toHaveLength(events.length);
  });

  it("keeps only telemetry-pipeline stages under Telemetry", () => {
    const events = [
      event("telemetry", "simulator_started"),
      event("telemetry", "mqtt_published"),
      event("telemetry", "telemetry_persisted"),
      event("rag_query", "query_received"),
    ];
    expect(phases(events, "telemetry")).toEqual([
      "simulator_started",
      "mqtt_published",
      "telemetry_persisted",
    ]);
  });

  it("overlaps Telemetry and Health on the health engine/snapshot stages", () => {
    const health = [
      event("health", "health_analysis_started"),
      event("health", "confidence_calculated"),
      event("health", "health_snapshot_created"),
    ];
    const events = [...health, event("telemetry", "telemetry_persisted")];

    // Health stages belong to the telemetry pipeline and the health pipeline.
    expect(phases(events, "telemetry")).toEqual([
      "health_analysis_started",
      "confidence_calculated",
      "health_snapshot_created",
      "telemetry_persisted",
    ]);
    expect(phases(events, "health")).toEqual([
      "health_analysis_started",
      "confidence_calculated",
      "health_snapshot_created",
    ]);
  });

  it("does not leak health stages into unrelated tabs", () => {
    const events = [
      event("health", "health_snapshot_created"),
      event("telemetry", "telemetry_persisted"),
    ];
    for (const tab of ["rag-ingestion", "rag-query", "agent", "simulation", "system"] as const) {
      expect(filterEventsByTab(events, tab)).toHaveLength(0);
    }
  });

  it("separates RAG ingestion from RAG query", () => {
    const events = [
      event("rag_ingestion", "document_parsed"),
      event("rag_ingestion", "embeddings_generated"),
      event("rag_ingestion", "ingestion_error"),
      event("rag_query", "query_embedding_completed"),
      event("rag_query", "reranking_completed"),
      event("rag_query", "rag_query_error"),
    ];
    expect(phases(events, "rag-ingestion")).toEqual([
      "document_parsed",
      "embeddings_generated",
      "ingestion_error",
    ]);
    expect(phases(events, "rag-query")).toEqual([
      "query_embedding_completed",
      "reranking_completed",
      "rag_query_error",
    ]);
  });

  it("matches agent execution stages, including contexts and errors", () => {
    const events = [
      event("agent", "supervisor_started"),
      event("agent", "vehicle_context_loaded"),
      event("agent", "health_context_loaded"),
      event("agent", "manufacturer_context_requested"),
      event("agent", "reasoning_started"),
      event("agent", "response_generated"),
      event("agent", "agent_error"),
      event("health", "health_snapshot_created"),
    ];
    expect(phases(events, "agent")).toEqual([
      "supervisor_started",
      "vehicle_context_loaded",
      "health_context_loaded",
      "manufacturer_context_requested",
      "reasoning_started",
      "response_generated",
      "agent_error",
    ]);
  });

  it("matches simulation lifecycle stages", () => {
    const events = [
      event("simulation", "simulation_start_requested"),
      event("simulation", "simulation_started"),
      event("simulation", "simulation_stopped"),
      event("simulation", "simulation_error"),
      event("telemetry", "simulator_started"),
    ];
    expect(phases(events, "simulation")).toEqual([
      "simulation_start_requested",
      "simulation_started",
      "simulation_stopped",
      "simulation_error",
    ]);
  });

  it("matches system lifecycle and infrastructure stages", () => {
    const events = [
      event("system", "subscriber_started"),
      event("system", "subscriber_error"),
      event("system", "stream_connected"),
      event("system", "stream_disconnected"),
      event("simulation", "simulation_started"),
    ];
    expect(phases(events, "system")).toEqual([
      "subscriber_started",
      "subscriber_error",
      "stream_connected",
      "stream_disconnected",
    ]);
  });

  it("falls back to stage mapping when the workflow value is unknown", () => {
    const legacy = event("legacy" as WorkflowType, "telemetry_persisted");
    const unknown = event("legacy" as WorkflowType, "a_stage_we_do_not_know" as WorkflowStage);
    expect(phases([legacy, unknown], "telemetry")).toEqual(["telemetry_persisted"]);
    expect(phases([legacy, unknown], "overview")).toEqual([
      "telemetry_persisted",
      "a_stage_we_do_not_know",
    ]);
  });

  it("exposes the resolved stage sets per tab", () => {
    expect(tabStages("telemetry").has("telemetry_error")).toBe(true);
    expect(tabStages("health").has("health_analysis_started")).toBe(true);
    expect(tabStages("system").has("stream_disconnected")).toBe(true);
    expect(tabStages("overview").size).toBe(0);
  });

  it("preserves source order and never mutates the input", () => {
    const events = [
      event("rag_query", "query_received"),
      event("telemetry", "telemetry_persisted"),
      event("rag_query", "answer_generated"),
    ];
    const snapshot = [...events];
    const result = filterEventsByTab(events, "rag-query");
    expect(result.map((e) => e.stage)).toEqual(["query_received", "answer_generated"]);
    expect(events).toEqual(snapshot);
    // Overview returns the same reference so consumers do not re-render.
    expect(filterEventsByTab(events, "overview")).toBe(events);
  });
});

import type { WorkflowEventResponse, WorkflowType } from "@/types/api";
import { PIPELINES, type PipelineId } from "./pipelines";

/**
 * Centralized mapping between the Workflow Monitor tabs and the workflow event
 * categories they display.
 *
 * The backend tags every event with an authoritative `workflow` value
 * (`app/schemas/workflow.py`). That field is the single most reliable signal, so
 * it drives classification. A stage->tab map (derived from the project's
 * `PIPELINES` registry, where the stage identifiers actually live) is kept as a
 * scoped fallback so an event is never dropped merely because its `workflow`
 * value is missing or unknown.
 *
 * The Telemetry and Health tabs intentionally overlap: the Telemetry pipeline
 * runs through the health-engine and health-snapshot stages, so those events
 * surface under both tabs. No other tab pairs share stages.
 */

export type WorkflowTab =
  | "overview"
  | "telemetry"
  | "rag-ingestion"
  | "rag-query"
  | "health"
  | "agent"
  | "simulation"
  | "system";

export const WORKFLOW_TABS: readonly WorkflowTab[] = [
  "overview",
  "telemetry",
  "rag-ingestion",
  "rag-query",
  "health",
  "agent",
  "simulation",
  "system",
];

/**
 * The canonical backend `workflow` value each tab represents. Overview has no
 * category of its own and deliberately shows every workflow.
 */
export const TAB_WORKFLOW: Record<WorkflowTab, WorkflowType | null> = {
  overview: null,
  telemetry: "telemetry",
  "rag-ingestion": "rag_ingestion",
  "rag-query": "rag_query",
  health: "health",
  agent: "agent",
  simulation: "simulation",
  system: "system",
};

/** Tabs backed by a `PIPELINES` entry (the stage registry lives there). */
const PIPELINE_FOR_TAB: Partial<Record<WorkflowTab, PipelineId>> = {
  telemetry: "telemetry",
  "rag-ingestion": "rag_ingestion",
  "rag-query": "rag_query",
  health: "health",
  agent: "agent",
};

/**
 * Stages that belong to a tab but are not declared on its `PIPELINES` entry.
 * Kept explicit so the fallback never silently regresses when a pipeline's node
 * list is trimmed for display reasons.
 */
const EXTRA_TAB_STAGES: Partial<Record<WorkflowTab, readonly string[]>> = {
  // The telemetry pipeline renders terminal error states from status, not a node.
  telemetry: ["telemetry_error"],
  // Health draws the analysis-start marker from status, not a node.
  health: ["health_analysis_started"],
};

/**
 * Simulation and System are lifecycle categories with no `PIPELINES` entry;
 * their stages come straight from the backend `WorkflowStage` enum.
 */
const STANDALONE_TAB_STAGES: Partial<Record<WorkflowTab, readonly string[]>> = {
  simulation: [
    "simulation_start_requested",
    "simulation_started",
    "simulation_restart_requested",
    "simulation_restarted",
    "simulation_stop_requested",
    "simulation_stopped",
    "simulation_error",
    "simulation_process_exit",
  ],
  system: [
    "subscriber_started",
    "subscriber_stopped",
    "subscriber_error",
    "stream_connected",
    "stream_disconnected",
  ],
};

function buildTabStages(): Record<WorkflowTab, ReadonlySet<string>> {
  const tables = {} as Record<WorkflowTab, ReadonlySet<string>>;
  for (const tab of WORKFLOW_TABS) {
    const stages = new Set<string>();
    const pipelineId = PIPELINE_FOR_TAB[tab];
    if (pipelineId) {
      for (const stage of PIPELINES[pipelineId].stages) {
        for (const eventStage of stage.eventStages) stages.add(eventStage);
      }
    }
    for (const stage of STANDALONE_TAB_STAGES[tab] ?? []) stages.add(stage);
    for (const stage of EXTRA_TAB_STAGES[tab] ?? []) stages.add(stage);
    tables[tab] = stages;
  }
  return tables;
}

/** Stage identifiers that map to each tab (fallback matching + tests). */
const TAB_STAGES: Record<WorkflowTab, ReadonlySet<string>> = buildTabStages();

export function tabStages(tab: WorkflowTab): ReadonlySet<string> {
  return TAB_STAGES[tab];
}

/**
 * True when an event belongs to the selected tab.
 *
 * Overview matches everything. Otherwise the event matches when its canonical
 * `workflow` equals the tab's category, or — as a fallback for unknown/missing
 * workflow values — when its `stage` is one of the tab's stages.
 */
export function eventMatchesTab(
  event: Pick<WorkflowEventResponse, "workflow" | "stage">,
  tab: WorkflowTab,
): boolean {
  if (tab === "overview") return true;
  const workflow = TAB_WORKFLOW[tab];
  if (workflow !== null && event.workflow === workflow) return true;
  return TAB_STAGES[tab].has(event.stage);
}

/**
 * Project a list of events down to the ones the selected tab displays. This is
 * a pure projection: the source list and its order are never mutated, so the
 * shared event buffer is unaffected by switching tabs.
 */
export function filterEventsByTab(
  events: WorkflowEventResponse[],
  tab: WorkflowTab,
): WorkflowEventResponse[] {
  if (tab === "overview") return events;
  return events.filter((event) => eventMatchesTab(event, tab));
}

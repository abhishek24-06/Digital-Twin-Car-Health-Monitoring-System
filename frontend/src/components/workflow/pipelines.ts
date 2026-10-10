import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Database,
  FileCode,
  FileSearch,
  FileText,
  Gauge,
  HardDrive,
  Layers,
  Link2,
  MessageSquare,
  Save,
  Scissors,
  Send,
  Server,
  Stethoscope,
  Target,
  TrendingUp,
  XCircle,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type {
  TelemetryStage,
  VehicleTelemetryState,
  WorkflowEventResponse,
} from "@/types/api";
import type { StageStatus } from "./status";

export type PipelineId =
  | "telemetry"
  | "rag_ingestion"
  | "rag_query"
  | "health"
  | "agent";

export interface StageDef {
  /** Stable key used only for React keys and derived-stage matching. */
  key: string;
  label: string;
  /** WorkflowEvent stages that map onto this node. */
  eventStages: string[];
  /** Derived telemetry stage that supersedes events for this node. */
  derivedStage?: TelemetryStage;
  icon?: LucideIcon;
}

export interface PipelineDef {
  id: PipelineId;
  title: string;
  orientation: "horizontal" | "vertical";
  stages: StageDef[];
}

export interface DeriveScope {
  /** The workflow whose events belong to this pipeline. */
  workflow: string;
  /** Optional derived telemetry snapshot (only meaningful for `telemetry`). */
  derivedState?: VehicleTelemetryState | null;
}

export interface DerivedStageState {
  stage: string;
  label: string;
  status: StageStatus;
  /** Explicit provenance so derived state is never shown as observed. */
  observation: "observed" | "derived" | "none-yet";
  lastEvent: WorkflowEventResponse | null;
  detail?: string;
  /** When the latest signal for this stage was observed (ISO-8601 UTC). */
  at?: string | null;
}

export const PIPELINES: Record<PipelineId, PipelineDef> = {
  telemetry: {
    id: "telemetry",
    title: "Telemetry Pipeline",
    orientation: "horizontal",
    stages: [
      {
        key: "simulator",
        label: "Simulator",
        eventStages: ["simulator_started", "telemetry_generated"],
        derivedStage: "simulator",
        icon: Cpu,
      },
      {
        key: "mqtt_publish",
        label: "MQTT Publish",
        eventStages: ["mqtt_publish_started", "mqtt_published"],
        derivedStage: "mqtt_publish",
        icon: Send,
      },
      {
        key: "mqtt_broker",
        label: "MQTT Broker",
        eventStages: [],
        derivedStage: "mqtt_broker",
        icon: Server,
      },
      {
        key: "mqtt_subscriber",
        label: "MQTT Subscriber",
        eventStages: ["mqtt_received"],
        derivedStage: "mqtt_subscriber",
        icon: Send,
      },
      {
        key: "parser",
        label: "Parser / Validator",
        eventStages: [
          "telemetry_parsed",
          "telemetry_validation_success",
          "telemetry_validation_error",
        ],
        derivedStage: "parser",
        icon: Cpu,
      },
      {
        key: "postgres",
        label: "PostgreSQL",
        eventStages: ["telemetry_persist_started", "telemetry_persisted"],
        derivedStage: "postgres",
        icon: Database,
      },
      {
        key: "health_engine",
        label: "Health Engine",
        eventStages: [
          "health_analysis_started",
          "telemetry_window_loaded",
          "data_sufficiency_evaluated",
          "baseline_comparison_completed",
          "rules_evaluated",
          "health_score_calculated",
          "confidence_calculated",
          "provisional_status_assigned",
        ],
        derivedStage: "health_engine",
        icon: Stethoscope,
      },
      {
        key: "health_snapshot",
        label: "Health Snapshot",
        eventStages: ["health_snapshot_created"],
        derivedStage: "health_snapshot",
        icon: HardDrive,
      },
    ],
  },
  rag_ingestion: {
    id: "rag_ingestion",
    title: "RAG Ingestion Pipeline",
    orientation: "vertical",
    stages: [
      {
        key: "upload",
        label: "Document Upload",
        eventStages: ["document_upload_started", "document_received"],
        icon: FileText,
      },
      {
        key: "parse",
        label: "Document Parse",
        eventStages: ["document_parse_started", "document_parsed"],
        icon: FileSearch,
      },
      {
        key: "extract",
        label: "Text Extraction",
        eventStages: ["text_extracted"],
        icon: FileCode,
      },
      {
        key: "sections",
        label: "Sections Detected",
        eventStages: ["sections_detected"],
        icon: Layers,
      },
      {
        key: "chunk",
        label: "Chunking",
        eventStages: ["chunking_started", "chunks_created"],
        icon: Scissors,
      },
      {
        key: "metadata",
        label: "Metadata Attached",
        eventStages: ["metadata_attached"],
        icon: Layers,
      },
      {
        key: "embedding",
        label: "Embedding Generation",
        eventStages: ["embedding_started", "embeddings_generated"],
        icon: Zap,
      },
      {
        key: "vector_storage",
        label: "Vector Storage (pgvector)",
        eventStages: ["vector_storage_started", "chunks_stored"],
        icon: Database,
      },
      {
        key: "index",
        label: "Index Ready",
        eventStages: ["index_ready"],
        icon: Save,
      },
      {
        key: "completed",
        label: "Ingestion Completed",
        eventStages: ["ingestion_completed"],
        icon: CheckCircle2,
      },
      {
        key: "error",
        label: "Ingestion Error",
        eventStages: ["ingestion_error"],
        icon: XCircle,
      },
    ],
  },
  rag_query: {
    id: "rag_query",
    title: "RAG Query Pipeline",
    orientation: "vertical",
    stages: [
      {
        key: "query",
        label: "Query Received",
        eventStages: ["query_received"],
        icon: MessageSquare,
      },
      {
        key: "embedding",
        label: "Query Embedding",
        eventStages: ["query_embedding_started", "query_embedding_completed"],
        icon: Zap,
      },
      {
        key: "vector_search",
        label: "Vector Search",
        eventStages: ["vector_search_started", "vector_search_completed"],
        icon: Database,
      },
      {
        key: "candidates",
        label: "Candidates Retrieved",
        eventStages: ["candidates_retrieved"],
        icon: Layers,
      },
      {
        key: "reranking",
        label: "Reranking",
        eventStages: ["reranking_started", "reranking_completed"],
        icon: Zap,
      },
      {
        key: "context",
        label: "Context Assembled",
        eventStages: ["context_assembled"],
        icon: FileText,
      },
      {
        key: "answer",
        label: "Answer Generated",
        eventStages: ["answer_generation_started", "answer_generated"],
        icon: MessageSquare,
      },
      {
        key: "sources",
        label: "Sources Attached",
        eventStages: ["sources_attached"],
        icon: Link2,
      },
      {
        key: "completed",
        label: "Query Completed",
        eventStages: ["rag_query_completed"],
        icon: CheckCircle2,
      },
      {
        key: "error",
        label: "Query Error",
        eventStages: ["rag_query_error"],
        icon: XCircle,
      },
    ],
  },
  health: {
    id: "health",
    title: "Health Pipeline",
    orientation: "vertical",
    stages: [
      {
        key: "window",
        label: "Telemetry Window",
        eventStages: ["telemetry_window_loaded"],
        icon: Database,
      },
      {
        key: "sufficiency",
        label: "Data Sufficiency",
        eventStages: ["data_sufficiency_evaluated"],
        icon: Gauge,
      },
      {
        key: "rules",
        label: "Rules Evaluated",
        eventStages: ["rules_evaluated"],
        icon: AlertTriangle,
      },
      {
        key: "baseline",
        label: "Baseline Comparison",
        eventStages: ["baseline_comparison_completed"],
        icon: TrendingUp,
      },
      {
        key: "score",
        label: "Health Score",
        eventStages: ["health_score_calculated"],
        icon: Target,
      },
      {
        key: "confidence",
        label: "Confidence",
        eventStages: ["confidence_calculated"],
        icon: Gauge,
      },
      {
        key: "provisional",
        label: "Provisional Status",
        eventStages: ["provisional_status_assigned"],
        icon: AlertTriangle,
      },
      {
        key: "snapshot",
        label: "Health Snapshot",
        eventStages: ["health_snapshot_created"],
        icon: Database,
      },
    ],
  },
  agent: {
    id: "agent",
    title: "Agent Pipeline",
    orientation: "vertical",
    stages: [
      {
        key: "request",
        label: "Agent Request Received",
        eventStages: ["agent_request_received"],
        icon: MessageSquare,
      },
      {
        key: "supervisor",
        label: "Supervisor",
        eventStages: ["supervisor_started", "supervisor_completed"],
        icon: Cpu,
      },
      {
        key: "vehicle_context",
        label: "Vehicle Context",
        eventStages: ["vehicle_context_loaded"],
        icon: Database,
      },
      {
        key: "health_context",
        label: "Health Context",
        eventStages: ["health_context_loaded"],
        icon: AlertTriangle,
      },
      {
        key: "manufacturer_context",
        label: "Manufacturer Context",
        eventStages: ["manufacturer_context_requested", "rag_context_received"],
        icon: FileText,
      },
      {
        key: "reasoning",
        label: "Reasoning",
        eventStages: ["reasoning_started"],
        icon: Cpu,
      },
      {
        key: "tools",
        label: "Tools Completed",
        eventStages: ["tool_completed"],
        icon: Zap,
      },
      {
        key: "response",
        label: "Response Generated",
        eventStages: ["response_generated"],
        icon: MessageSquare,
      },
      {
        key: "completed",
        label: "Agent Completed",
        eventStages: ["agent_completed"],
        icon: CheckCircle2,
      },
      {
        key: "error",
        label: "Agent Error",
        eventStages: ["agent_error"],
        icon: XCircle,
      },
    ],
  },
};

function newestEventForStage(
  events: WorkflowEventResponse[],
  eventStages: string[],
): { event: WorkflowEventResponse | null } {
  if (eventStages.length === 0) return { event: null };
  const allowed = new Set(eventStages);
  let newest: WorkflowEventResponse | null = null;
  for (const event of events) {
    if (!allowed.has(event.stage)) continue;
    if (newest === null || event.timestamp > newest.timestamp) {
      newest = event;
    }
  }
  return { event: newest };
}

/**
 * Fold raw events (and, for telemetry, a derived snapshot) into per-stage
 * states. Nothing here invents progress: a stage with no signal stays
 * `waiting`, and derived state is always labelled as derived.
 */
export function deriveStageStates(
  events: WorkflowEventResponse[],
  stages: StageDef[],
  scope: DeriveScope,
): DerivedStageState[] {
  const relevant = events.filter((event) => event.workflow === scope.workflow);
  const derivedByStage = new Map(
    (scope.derivedState?.stages ?? []).map((state) => [state.stage, state]),
  );
  // A present derived snapshot is authoritative for every stage that has a
  // derived counterpart. An omitted stage means "no real signal yet", so we
  // must NOT fall back to an older observed event -- doing so is how a stale
  // "success" from a previous run survived after the backend had already gone
  // degraded. Only pipelines without a derived snapshot use events.
  const derivedAuthoritative = scope.derivedState != null;

  return stages.map((def) => {
    const derived = def.derivedStage
      ? derivedByStage.get(def.derivedStage)
      : undefined;

    if (derived) {
      return {
        stage: def.key,
        label: def.label,
        status: derived.status as StageStatus,
        observation: "derived" as const,
        lastEvent: null,
        detail: derived.detail ?? undefined,
        at: derived.at ?? null,
      };
    }

    if (derivedAuthoritative && def.derivedStage) {
      return {
        stage: def.key,
        label: def.label,
        status: "waiting" as StageStatus,
        observation: "none-yet" as const,
        lastEvent: null,
        at: null,
      };
    }

    const { event } = newestEventForStage(relevant, def.eventStages);
    if (!event) {
      return {
        stage: def.key,
        label: def.label,
        status: "waiting" as StageStatus,
        observation: "none-yet" as const,
        lastEvent: null,
        at: null,
      };
    }

    return {
      stage: def.key,
      label: def.label,
      status: event.status as StageStatus,
      observation: "observed" as const,
      lastEvent: event,
      at: event.timestamp,
    };
  });
}

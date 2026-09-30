/**
 * TypeScript mirrors of the Digital Twin backend contract.
 *
 * Every shape here was read from the live `backend/openapi.json` and the
 * backend Pydantic schemas (`app/schemas/*`, `app/intelligence/models.py`,
 * `app/agent/schemas.py`, `app/rag/schemas.py`). Do not invent fields: if the
 * backend does not return them, they are not here.
 */

/* ---------------------------------------------------------------- */
/* Primitives + envelopes                                            */
/* ---------------------------------------------------------------- */

export type UUID = string;

/** ISO 8601 timestamp string, always UTC-suffixed (`2026-01-01T00:00:00Z`). */
export type IsoDateTime = string;

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

/** FastAPI validation error as returned by the global 422 handler. */
export interface ValidationErrorItem {
  type: string;
  loc: string[];
  msg: string;
  input?: unknown;
}

export interface ApiErrorBody {
  detail: string | ValidationErrorItem[];
  error_code?: string;
}

/* ---------------------------------------------------------------- */
/* Auth + user                                                       */
/* ---------------------------------------------------------------- */

export type UserRole = "user" | "admin";

export interface UserResponse {
  id: UUID;
  email: string;
  role: UserRole;
  full_name: string | null;
  is_active: boolean;
  created_at: IsoDateTime;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserResponse;
}

export interface UserProfileUpdate {
  full_name?: string | null;
}

/**
 * Shape returned by the Next.js session proxy (`/api/session*`). When
 * `authenticated` is false the other fields are absent — that is a signed-out
 * response, not an error.
 */
export interface SessionResponse {
  authenticated: boolean;
  access_token?: string;
  /** ISO timestamp; derived from the JWT `exp` claim or `expires_in`. */
  expires_at?: string;
  expires_in?: number;
  user?: UserResponse;
}

/* ---------------------------------------------------------------- */
/* Vehicles                                                          */
/* ---------------------------------------------------------------- */

export interface VehicleResponse {
  id: UUID;
  vin: string;
  make: string;
  model: string;
  year: number;
  engine_type: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  owner_user_id: UUID | null;
  source_type: string;
  status: string;
  simulation_enabled: boolean;
}

export interface VehicleCreate {
  vin: string;
  make: string;
  model: string;
  year: number;
  engine_type?: string | null;
}

export interface VehicleUpdate {
  make?: string;
  model?: string;
  year?: number;
  engine_type?: string | null;
}

/* ---------------------------------------------------------------- */
/* Telemetry                                                         */
/* ---------------------------------------------------------------- */

export interface TelemetryResponse {
  id: UUID;
  vehicle_id: UUID;
  timestamp: IsoDateTime;
  rpm: number | null;
  speed: number | null;
  engine_load: number | null;
  coolant_temperature: number | null;
  oil_temperature: number | null;
  battery_voltage: number | null;
  fuel_level: number | null;
  intake_air_temperature: number | null;
  throttle_position: number | null;
  engine_runtime: number | null;
  odometer: number | null;
  raw_payload: Record<string, unknown> | null;
  source_event_id: string | null;
  created_at: IsoDateTime;
}

export interface TelemetryCreate {
  timestamp: IsoDateTime;
  rpm?: number | null;
  speed?: number | null;
  engine_load?: number | null;
  coolant_temperature?: number | null;
  oil_temperature?: number | null;
  battery_voltage?: number | null;
  fuel_level?: number | null;
  intake_air_temperature?: number | null;
  throttle_position?: number | null;
  engine_runtime?: number | null;
  odometer?: number | null;
  source_event_id?: string | null;
}

/* ---------------------------------------------------------------- */
/* Vehicle health context (Phase 3 deterministic engine)             */
/* ---------------------------------------------------------------- */

export type HealthStatus = "healthy" | "attention" | "critical" | "unknown";
export type Severity = "info" | "warning" | "critical";
export type TrendDirection =
  | "increasing"
  | "decreasing"
  | "stable"
  | "insufficient_data";
export type TrendStrength = "none" | "weak" | "moderate" | "strong";
export type BaselineStatus =
  | "within"
  | "elevated"
  | "depressed"
  | "insufficient_history";

export interface AnalysisWindow {
  start: IsoDateTime;
  end: IsoDateTime;
  window_minutes: number;
}

export interface MetricStatistics {
  metric: string;
  unit: string;
  count: number;
  minimum: number | null;
  maximum: number | null;
  mean: number | null;
  median: number | null;
  std_dev: number | null;
  first: number | null;
  last: number | null;
  range: number | null;
  percentile_25: number | null;
  percentile_75: number | null;
  coefficient_of_variation: number | null;
}

export interface DataQuality {
  sample_count: number;
  expected_sample_count: number;
  coverage_ratio: number | null;
  first_timestamp: IsoDateTime | null;
  last_timestamp: IsoDateTime | null;
  duration_seconds: number | null;
  missing_sample_estimate: number;
  max_gap_seconds: number | null;
  timestamp_order_valid: boolean;
}

export interface TrendInsight {
  metric: string;
  unit: string;
  direction: TrendDirection;
  slope: number | null;
  normalized_slope: number | null;
  strength: TrendStrength | null;
  sample_count: number;
}

export interface BaselineInsight {
  metric: string;
  unit: string;
  center: number | null;
  spread: number | null;
  sample_count: number;
  current_value: number | null;
  normalized_deviation: number | null;
  status: BaselineStatus;
  note: string | null;
}

export interface Finding {
  rule_id: string;
  severity: Severity;
  category: string;
  metric: string | null;
  observed_value: number | null;
  threshold: number | null;
  unit: string | null;
  message: string;
  confidence: number | null;
  evidence: Record<string, unknown>;
  window_start: IsoDateTime | null;
  window_end: IsoDateTime | null;
}

export interface PenaltyComponent {
  category: string;
  severity: Severity;
  finding_count: number;
  penalty: number;
  capped: boolean;
}

export interface ScoreDetails {
  score: number | null;
  status: HealthStatus;
  starting_score: number;
  total_penalty: number;
  components: PenaltyComponent[];
  notes: string[];
}

export interface HealthContextResponse {
  vehicle_id: UUID;
  context_schema_version: string;
  rule_engine_version: string;
  generated_at: IsoDateTime;
  analysis_duration_ms: number | null;
  analysis_window: AnalysisWindow;
  data_quality: DataQuality;
  statistics: Record<string, MetricStatistics>;
  trends: TrendInsight[];
  baselines: BaselineInsight[];
  findings: Finding[];
  health_score: number | null;
  health_status: HealthStatus;
  confidence: number | null;
  score_details: ScoreDetails;
}

export interface HealthSnapshotItem {
  id: UUID;
  vehicle_id: UUID;
  generated_at: IsoDateTime;
  window_start: IsoDateTime;
  window_end: IsoDateTime;
  sample_count: number;
  health_score: number | null;
  health_status: HealthStatus;
  confidence: number | null;
  context_schema_version: string;
}

/* ---------------------------------------------------------------- */
/* Agent diagnosis (Phase 4)                                         */
/* ---------------------------------------------------------------- */

export type Likelihood = "high" | "medium" | "low";
export type ActionPriority = "immediate" | "high" | "medium" | "low";
export type ActionCategory =
  | "mechanical"
  | "inspection"
  | "logistics"
  | "operator"
  | "other";

export interface EvidenceItem {
  rule_id: string | null;
  metric: string | null;
  observed_value: number | null;
  threshold: number | null;
  unit: string | null;
  message: string;
  severity: Severity | null;
}

export interface Hypothesis {
  cause: string;
  likelihood: Likelihood;
  matching_evidence: string[];
  recommended_actions: string[];
}

export interface RecommendedAction {
  action: string;
  priority: ActionPriority;
  category: ActionCategory;
}

export interface SeverityAnalysis {
  assessed_severity: Severity;
  rule_severity: Severity;
  rationale: string;
}

export interface ConfidenceAnalysis {
  assessed_confidence: number;
  deterministic_confidence: number;
  score_quality: string;
  data_quality: string;
  rationale: string;
  validation_warnings: string[];
}

export interface Citation {
  index: number;
  document_id: UUID;
  document_version_id: UUID;
  document_version: number;
  chunk_id: UUID;
  source_filename: string | null;
  title: string;
  section_title: string;
  page_start: number | null;
  page_end: number | null;
}

export interface ManufacturerEvidence {
  index: number;
  source_filename: string | null;
  title: string;
  section_title: string;
  page_start: number | null;
  page_end: number | null;
  scope: string | null;
  dense_score: number | null;
  lexical_score: number | null;
  hybrid_score: number | null;
  rerank_score: number | null;
  excerpt: string;
}

export interface DiagnosisContent {
  summary: string;
  possible_causes: Hypothesis[];
  recommended_actions: RecommendedAction[];
  evidence: EvidenceItem[];
  severity_analysis: SeverityAnalysis;
  confidence_analysis: ConfidenceAnalysis;
  context_note: string;
  manufacturer_guidance: string;
  cited_sources: number[];
  citations: Citation[];
  manufacturer_evidence: ManufacturerEvidence[];
}

export interface ExecutionMetadata {
  latency_ms: number;
  provider: string;
  model: string;
  fallback_used: boolean;
  fallback_reason: string | null;
  input_tokens: number;
  output_tokens: number;
  attempts: number;
  deduplicated: boolean;
  rule_ids: string[];
  rag_used: boolean;
  rag_evidence_count: number;
  rag_embedding_model: string | null;
  rag_reranker_model: string | null;
  rag_scope: Record<string, unknown>;
  rag_reason: string;
}

export interface DiagnosisResponse {
  id: UUID | null;
  vehicle_id: UUID;
  trigger_type: string;
  user_query: string;
  diagnosis: DiagnosisContent;
  severity: Severity;
  confidence: number;
  context_timestamp: IsoDateTime | null;
  generated_at: IsoDateTime;
  execution: ExecutionMetadata;
}

export interface AgentDiagnosisItem {
  id: UUID;
  vehicle_id: UUID;
  trigger_type: string;
  severity: Severity;
  confidence: number | null;
  status: string;
  error_code: string | null;
  provider: string | null;
  model: string | null;
  fallback_used: boolean;
  latency_ms: number | null;
  rag_used: boolean;
  rag_evidence_count: number;
  rag_embedding_model: string | null;
  rag_reranker_model: string | null;
  user_id: UUID | null;
  created_at: IsoDateTime;
}

export interface DashboardResponse {
  vehicle_id: UUID;
  generated_at: IsoDateTime;
  health_context: HealthContextResponse | null;
  latest_diagnosis: DiagnosisResponse | null;
  diagnosis_age_seconds: number | null;
}

/* ---------------------------------------------------------------- */
/* RAG (Phase 5 read-only + Phase 6.x admin)                         */
/* ---------------------------------------------------------------- */

export type ScopeTier = "EXACT_VEHICLE" | "MODEL" | "MAKE" | "GENERIC";

export interface VehicleScope {
  make: string | null;
  model: string | null;
  year: number | null;
  engine: string | null;
  region: string | null;
}

export interface RetrievedEvidence {
  chunk_id: UUID;
  document_id: UUID;
  document_version_id: UUID;
  document_version: number;
  title: string;
  manufacturer: string | null;
  make: string | null;
  model: string | null;
  model_year_start: number | null;
  model_year_end: number | null;
  document_type: string;
  source_filename: string | null;
  section_title: string;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  content: string;
  scope: ScopeTier;
  dense_score: number | null;
  lexical_score: number | null;
  hybrid_score: number | null;
  rerank_score: number | null;
  metadata: Record<string, unknown>;
}

export interface RAGSearchResult {
  query: string;
  vehicle_scope: VehicleScope | null;
  results: RetrievedEvidence[];
  available: boolean;
  reason: string;
  metrics: Record<string, unknown>;
}

export interface RagHealthResponse {
  rag_enabled: boolean;
  pgvector_available: boolean;
  embedding_adapter: Record<string, unknown>;
  reranker_adapter: Record<string, unknown>;
  embedding_model: string | null;
  embedding_dimension: number | null;
  corpus_documents: number;
  corpus_versions: number;
  corpus_completed_chunks: number;
}

export interface RagDocumentSummary {
  id: UUID;
  source_type: string;
  canonical_source: string | null;
  source_uri: string | null;
  manufacturer: string | null;
  make: string | null;
  model: string | null;
  model_year_start: number | null;
  model_year_end: number | null;
  document_type: string;
  title: string;
  language: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  version_count: number;
}

export interface RagVersionSummary {
  id: UUID;
  document_id: UUID;
  version: number;
  content_hash: string;
  source_filename: string;
  parser_name: string;
  parser_version: string | null;
  language: string | null;
  page_count: number | null;
  embedding_model: string;
  embedding_dimension: number;
  chunking_version: string;
  ingestion_status: string;
  error_message: string | null;
  created_at: IsoDateTime;
  chunk_count: number;
}

export interface RagDocumentDetail extends RagDocumentSummary {
  versions: RagVersionSummary[];
  latest_version: RagVersionSummary | null;
}

export interface AdminRagUploadResponse {
  id: UUID | null;
  status: "ingested" | "unchanged";
  filename: string;
  canonical: string;
  make: string | null;
  model: string | null;
  year: number | null;
  version: number | null;
  chunks_created: number;
  content_hash: string;
  parser_name: string | null;
  embedding_model: string | null;
  embedding_dimension: number | null;
}

export interface AdminRagUploadForm {
  canonical: string;
  make?: string;
  model?: string;
  year?: number;
  manufacturer?: string;
  title?: string;
  source_uri?: string;
  source_type?: string;
  document_type?: string;
  year_end?: number;
  language?: string;
}

/* ---------------------------------------------------------------- */
/* Service health                                                    */
/* ---------------------------------------------------------------- */

export interface HealthResponse {
  status: string;
  service: string;
}

export interface HealthDbResponse {
  status: string;
  service: string;
  database: string;
}
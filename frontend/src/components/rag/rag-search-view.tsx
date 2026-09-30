"use client";

import * as React from "react";
import { BookOpen, FileText, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { PageHeader } from "@/components/layout/page-header";
import { ragApi } from "@/services/rag";
import { toApiError } from "@/lib/api-error";
import { useActiveVehicleId } from "@/hooks/use-active-vehicle";
import { useVehicles } from "@/hooks/use-vehicle-data";
import { SCOPE_LABEL } from "@/lib/metrics";
import type { RAGSearchResult, RetrievedEvidence } from "@/types/api";

/**
 * Manufacturer guidance search.
 *
 * The API returns `available: false` with a `reason` when retrieval is disabled
 * or the corpus is unusable. That is presented as an explicit unavailable state
 * — never as "0 results found", which would look like a failed search.
 */
export function RagSearchView() {
  const { vehicleId } = useActiveVehicleId();
  const { data: vehicles } = useVehicles();
  const activeVehicle = React.useMemo(
    () => vehicles?.find((vehicle) => vehicle.id === vehicleId) ?? null,
    [vehicles, vehicleId],
  );

  const [query, setQuery] = React.useState("");
  const [make, setMake] = React.useState("");
  const [model, setModel] = React.useState("");
  const [year, setYear] = React.useState("");
  const [scopeToVehicle, setScopeToVehicle] = React.useState(true);
  const [result, setResult] = React.useState<RAGSearchResult | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [loading, setLoading] = React.useState(false);

  const runSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length === 0) return;

    setLoading(true);
    setError(null);
    try {
      const payload = await ragApi.search({
        q: trimmed,
        // Empty fields fall back to the active vehicle when the toggle is on.
        make: make.trim() || (scopeToVehicle ? activeVehicle?.make : undefined),
        model: model.trim() || (scopeToVehicle ? activeVehicle?.model : undefined),
        year: year
          ? Number(year)
          : scopeToVehicle
            ? activeVehicle?.year
            : undefined,
      });
      setResult(payload);
    } catch (caught) {
      setResult(null);
      setError(caught);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Manufacturer guidance"
        description="Search the ingested documentation corpus. Retrieval is scoped by make, model and year, so more specific queries return more relevant passages."
      />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Search the corpus</CardTitle>
            <CardDescription>
              Returns passages with their source document, section and page range
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={runSearch} noValidate className="space-y-4">
            <Field
              label="Question or phrase"
              htmlFor="rag-query"
              required
              hint="Up to 500 characters. Natural language works best."
            >
              <Input
                id="rag-query"
                value={query}
                maxLength={500}
                placeholder="e.g. coolant temperature sensor calibration interval"
                onChange={(event) => setQuery(event.target.value)}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Make" htmlFor="rag-make" hint="Optional filter">
                <Input
                  id="rag-make"
                  value={make}
                  maxLength={64}
                  placeholder="Honda"
                  onChange={(event) => setMake(event.target.value)}
                />
              </Field>
              <Field label="Model" htmlFor="rag-model" hint="Optional filter">
                <Input
                  id="rag-model"
                  value={model}
                  maxLength={128}
                  placeholder="Civic"
                  onChange={(event) => setModel(event.target.value)}
                />
              </Field>
              <Field label="Year" htmlFor="rag-year" hint="1900–2100">
                <Input
                  id="rag-year"
                  type="number"
                  inputMode="numeric"
                  min={1900}
                  max={2100}
                  value={year}
                  onChange={(event) => setYear(event.target.value)}
                  placeholder="2019"
                />
              </Field>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={scopeToVehicle}
                  onChange={(event) => setScopeToVehicle(event.target.checked)}
                  className="size-3.5 rounded border-line accent-[color:var(--signal-500)]"
                />
                {activeVehicle
                  ? `Scope to ${activeVehicle.make} ${activeVehicle.model} ${activeVehicle.year} where a field is empty`
                  : "Scope to the active vehicle where a field is empty"}
              </label>
              <Button type="submit" loading={loading}>
                <Search aria-hidden />
                Search
              </Button>
            </div>

            {error ? <ErrorState error={toApiError(error)} /> : null}
          </form>
        </CardContent>
      </Card>

      {result ? <RagResults result={result} /> : null}
    </div>
  );
}

/**
 * Result panel.
 *
 * On the real API, retrieval being *broken* arrives as a 503 from
 * `GET /rag/search` (RAG disabled, or pgvector/models missing) and is rendered
 * as an error by the caller. A 200 means the search ran, so `available: false`
 * with `reason: "hybrid"` simply means no passage matched — that is an empty
 * state, not an outage.
 */
function RagResults({ result }: { result: RAGSearchResult }) {
  if (!result.available && result.reason === "empty-query") {
    return (
      <InlineAlert tone="attention" title="Enter a question">
        The search needs a phrase to look for in the corpus.
      </InlineAlert>
    );
  }

  if (!result.available || result.results.length === 0) {
    return (
      <EmptyState
        icon={<BookOpen className="size-5" aria-hidden />}
        title="No passages matched"
        description={
          <>
            The corpus was searched successfully but nothing matched{" "}
            <span className="text-ink-muted">“{result.query}”</span>. Try fewer filters or a
            broader phrasing.
          </>
        }
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>
            {result.results.length} passage{result.results.length === 1 ? "" : "s"}
          </CardTitle>
          <CardDescription>
            Ranked by hybrid retrieval and reranking. Quotes are verbatim corpus text.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {result.vehicle_scope ? (
          <p className="text-[0.68rem] text-ink-subtle">
            scope: {[result.vehicle_scope.make, result.vehicle_scope.model, result.vehicle_scope.year]
              .filter(Boolean)
              .join(" · ") || "unscoped"}
          </p>
        ) : null}
        <ol className="space-y-3">
          {result.results.map((evidence, index) => (
            <li key={evidence.chunk_id}>
              <EvidenceCard evidence={evidence} rank={index + 1} />
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function EvidenceCard({
  evidence,
  rank,
}: {
  evidence: RetrievedEvidence;
  rank: number;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const excerpt = evidence.content.trim();
  const preview = excerpt.length > 260 ? `${excerpt.slice(0, 260)}…` : excerpt;

  return (
    <article className="rounded-lg border border-line bg-surface-2">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-3 py-2.5">
        <span className="tabular grid size-6 shrink-0 place-items-center rounded bg-surface-3 text-[0.68rem] font-semibold text-ink-muted">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-1.5 truncate text-sm font-medium text-ink">
            <FileText className="size-3.5 shrink-0 text-ink-subtle" aria-hidden />
            {evidence.title}
          </h3>
          <p className="mt-0.5 truncate text-xs text-ink-subtle">
            {evidence.section_title || "unsectioned"}
            {evidence.source_filename ? ` · ${evidence.source_filename}` : ""}
            {evidence.page_start != null
              ? ` · p.${evidence.page_start}${
                  evidence.page_end && evidence.page_end !== evidence.page_start
                    ? `–${evidence.page_end}`
                    : ""
                }`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge tone="neutral" size="sm">
            {SCOPE_LABEL[evidence.scope] ?? evidence.scope}
          </Badge>
          {evidence.rerank_score != null ? (
            <span className="tabular text-[0.65rem] text-ink-subtle">
              score {evidence.rerank_score.toFixed(3)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="px-3 py-2.5">
        <blockquote className="border-l-2 border-signal-500/40 pl-3 text-xs leading-relaxed text-ink-muted">
          {expanded ? excerpt : preview}
        </blockquote>
        {excerpt.length > 260 ? (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="mt-1.5 rounded text-[0.68rem] text-signal-400 underline-offset-4 hover:underline"
          >
            {expanded ? "Show less" : "Show full passage"}
          </button>
        ) : null}

        <div className="tabular mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.62rem] text-ink-subtle">
          {evidence.hybrid_score != null ? (
            <span>hybrid {evidence.hybrid_score.toFixed(3)}</span>
          ) : null}
          {evidence.dense_score != null ? (
            <span>dense {evidence.dense_score.toFixed(3)}</span>
          ) : null}
          {evidence.lexical_score != null ? (
            <span>lexical {evidence.lexical_score.toFixed(3)}</span>
          ) : null}
          <span>doc v{evidence.document_version}</span>
          {evidence.heading_path.length > 0 ? (
            <span className="truncate">› {evidence.heading_path.join(" › ")}</span>
          ) : null}
        </div>
      </div>
    </article>
  );
}


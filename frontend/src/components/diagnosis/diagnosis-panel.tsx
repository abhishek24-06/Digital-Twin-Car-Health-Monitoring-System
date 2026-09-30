"use client";

import * as React from "react";
import {
  Bot,
  BookOpen,
  Clock3,
  Gauge,
  Lightbulb,
  Quote,
  Send,
  ShieldQuestion,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { SeverityBadge } from "@/components/health/health-visuals";
import { cn } from "@/lib/utils";
import { metricLabel, metricMeta } from "@/lib/metrics";
import type { DiagnosisResponse } from "@/types/api";

const TRIGGER_LABEL: Record<string, string> = {
  user_query: "Your question",
  critical_event: "Critical telemetry event",
  critical_rule_event: "Critical telemetry event",
};

/**
 * Grounded AI diagnosis panel.
 *
 * Distinguishes two very different things the API can return:
 *  - a real diagnosis (`DiagnosisResponse`) from the reasoning agent, which may
 *    itself have used the deterministic fallback path (`execution.fallback_used`);
 *  - a failure to reach the provider (HTTP 502), rendered as an error state.
 * The AI output is always labelled as interpretation, never as a measurement.
 */
export function DiagnosisPanel({
  diagnosis,
  isAsking,
  askError,
  onAsk,
  className,
  suggestedQuestion,
}: {
  diagnosis: DiagnosisResponse | null;
  isAsking: boolean;
  askError: unknown;
  onAsk: (question: string) => void;
  className?: string;
  suggestedQuestion?: string;
}) {
  const [question, setQuestion] = React.useState("");
  const canSubmit = question.trim().length >= 3 && !isAsking;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    onAsk(question.trim());
    setQuestion("");
  };

  return (
    <div className={cn("space-y-4", className)}>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Ask about this vehicle</CardTitle>
            <CardDescription>
              The agent reads the latest Health Context and cites its sources.
            </CardDescription>
          </div>
        </CardHeader>
        <form onSubmit={submit}>
          <CardContent className="space-y-3">
            <label htmlFor="agent-question" className="sr-only">
              Question about this vehicle
            </label>
            <Textarea
              id="agent-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={2}
              placeholder={
                suggestedQuestion ??
                "e.g. Why is my coolant temperature trending up?"
              }
              maxLength={1000}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[0.68rem] text-ink-subtle">
                Requires a configured AI provider. Vehicle data is never modified.
              </p>
              <Button type="submit" size="sm" loading={isAsking} disabled={!canSubmit}>
                <Send aria-hidden />
                Ask the agent
              </Button>
            </div>
            {askError ? <ErrorState error={askError} compact /> : null}
          </CardContent>
        </form>
      </Card>

      {diagnosis ? (
        <DiagnosisCard diagnosis={diagnosis} />
      ) : (
        <EmptyState
          icon={<Bot className="size-5" aria-hidden />}
          title="No diagnosis yet"
          description={
            askError
              ? "The agent could not complete a diagnosis. The provider error is shown above; vehicle telemetry and the rule-based health score are unaffected."
              : "Ask a question above, or wait for the ingestion pipeline to trigger a critical-event diagnosis. Every diagnosis is persisted and listed under History."
          }
        />
      )}
    </div>
  );
}

export function DiagnosisCard({
  diagnosis,
  className,
}: {
  diagnosis: DiagnosisResponse;
  className?: string;
}) {
  // The backend's DiagnosisContent declares no required fields, so every list is
  // treated as possibly-absent rather than assumed.
  const content = diagnosis.diagnosis;
  const causes = content.possible_causes ?? [];
  const actions = content.recommended_actions ?? [];
  const trigger = TRIGGER_LABEL[diagnosis.trigger_type] ?? diagnosis.trigger_type;
  const usedFallback = diagnosis.execution?.fallback_used ?? false;

  return (
    <Card className={className}>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={diagnosis.severity} />
            <span className="text-ink-muted">{trigger}</span>
          </CardTitle>
          <CardDescription className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1">
              <Clock3 className="size-3" aria-hidden />
              {new Date(diagnosis.generated_at).toLocaleString()}
            </span>
            <span className="inline-flex items-center gap-1">
              <Gauge className="size-3" aria-hidden />
              confidence {(diagnosis.confidence * 100).toFixed(0)}%
            </span>
            <span className="inline-flex items-center gap-1">
              <Bot className="size-3" aria-hidden />
              {diagnosis.execution.provider}
              {diagnosis.execution.model ? ` · ${diagnosis.execution.model}` : ""}
            </span>
            {diagnosis.execution.rag_used ? (
              <span className="inline-flex items-center gap-1">
                <BookOpen className="size-3" aria-hidden />
                {diagnosis.execution.rag_evidence_count} doc references
              </span>
            ) : null}
          </CardDescription>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {usedFallback ? (
          <InlineAlert tone="attention" title="Deterministic fallback used">
            The AI provider could not be used, so this summary was assembled from the
            rule engine instead
            {diagnosis.execution.fallback_reason
              ? ` (${diagnosis.execution.fallback_reason})`
              : ""}
            . It is still derived from stored telemetry.
          </InlineAlert>
        ) : null}

        {diagnosis.user_query ? (
          <blockquote className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs italic text-ink-muted">
            “{diagnosis.user_query}”
          </blockquote>
        ) : null}

        <section aria-labelledby="diagnosis-summary">
          <h3 id="diagnosis-summary" className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
            Summary
          </h3>
          <p className="text-sm leading-relaxed text-ink">{content.summary}</p>
        </section>

        {causes.length > 0 ? (
          <section aria-labelledby="diagnosis-causes">
            <h3 id="diagnosis-causes" className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
              Possible causes
            </h3>
            <ul className="space-y-2.5">
              {causes.map((hypothesis, index) => (
                <li
                  key={`${hypothesis.cause}-${index}`}
                  className="rounded-lg border border-line bg-surface-2 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-ink">{hypothesis.cause}</p>
                    <LikelihoodBadge likelihood={hypothesis.likelihood} />
                  </div>
                  {hypothesis.matching_evidence.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {hypothesis.matching_evidence.map((item, itemIndex) => (
                        <li
                          key={`${item}-${itemIndex}`}
                          className="flex gap-1.5 text-xs leading-relaxed text-ink-muted"
                        >
                          <span className="mt-1.5 size-1 shrink-0 rounded-full bg-ink-subtle" aria-hidden />
                          {item}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {hypothesis.recommended_actions.length > 0 ? (
                    <p className="mt-2 text-xs text-ink-subtle">
                      Suggested: {hypothesis.recommended_actions.join(" · ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {actions.length > 0 ? (
          <section aria-labelledby="diagnosis-actions">
            <h3 id="diagnosis-actions" className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
              Recommended actions
            </h3>
            <ol className="space-y-2">
              {actions.slice()
                .sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority])
                .map((action, index) => (
                  <li
                    key={`${action.action}-${index}`}
                    className="flex gap-2.5 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
                  >
                    <Lightbulb
                      className="mt-0.5 size-3.5 shrink-0 text-[color:var(--color-attention)]"
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-snug text-ink">{action.action}</p>
                      <p className="mt-1 text-[0.65rem] uppercase tracking-wider text-ink-subtle">
                        {action.priority} · {action.category}
                      </p>
                    </div>
                  </li>
                ))}
            </ol>
          </section>
        ) : null}

        {(content.evidence ?? []).length > 0 ? (
          <section aria-labelledby="diagnosis-evidence">
            <h3 id="diagnosis-evidence" className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
              Evidence
            </h3>
            <ul className="space-y-1.5">
              {content.evidence.map((item, index) => {
                const meta = item.metric ? metricMeta(item.metric) : undefined;
                const decimals = meta?.decimals ?? 1;
                return (
                  <li
                    key={`${item.rule_id ?? "evidence"}-${index}`}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs"
                  >
                    {item.severity ? <SeverityBadge severity={item.severity} /> : null}
                    <span className="text-ink-muted">{item.message}</span>
                    <span className="tabular ml-auto text-[0.65rem] text-ink-subtle">
                      {item.metric ? `${metricLabel(item.metric)} ` : ""}
                      {item.observed_value !== null
                        ? `${item.observed_value.toFixed(decimals)}${
                            item.unit ?? meta?.unit ? ` ${item.unit ?? meta?.unit}` : ""
                          }`
                        : "—"}
                      {item.threshold !== null
                        ? ` / thr ${item.threshold.toFixed(decimals)}`
                        : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {content.manufacturer_guidance ? (
          <section aria-labelledby="diagnosis-guidance">
            <h3 id="diagnosis-guidance" className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
              Manufacturer guidance
            </h3>
            <p className="rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-ink-muted">
              {content.manufacturer_guidance}
            </p>
          </section>
        ) : null}

        {(content.citations ?? []).length > 0 ? (
          <Citations
            citations={content.citations}
            citedIndexes={content.cited_sources}
          />
        ) : null}

        <dl className="grid gap-3 border-t border-line pt-4 text-[0.68rem] sm:grid-cols-2">
          <div>
            <dt className="font-medium uppercase tracking-wider text-ink-subtle">
              Severity assessment
            </dt>
            <dd className="mt-0.5 leading-relaxed text-ink-muted">
              {content.severity_analysis.rationale}
            </dd>
          </div>
          <div>
            <dt className="font-medium uppercase tracking-wider text-ink-subtle">
              Confidence assessment
            </dt>
            <dd className="mt-0.5 leading-relaxed text-ink-muted">
              {content.confidence_analysis.rationale}
            </dd>
          </div>
          {content.confidence_analysis.validation_warnings.length > 0 ? (
            <div className="sm:col-span-2">
              <dt className="inline-flex items-center gap-1 font-medium uppercase tracking-wider text-ink-subtle">
                <ShieldQuestion className="size-3" aria-hidden />
                Validation warnings
              </dt>
              <dd className="mt-0.5">
                <ul className="list-disc space-y-0.5 pl-4 text-ink-muted">
                  {content.confidence_analysis.validation_warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </dd>
            </div>
          ) : null}
          {content.context_note ? (
            <div className="sm:col-span-2">
              <dt className="font-medium uppercase tracking-wider text-ink-subtle">
                Context note
              </dt>
              <dd className="mt-0.5 leading-relaxed text-ink-muted">{content.context_note}</dd>
            </div>
          ) : null}
        </dl>
      </CardContent>

      <CardFooter className="justify-between gap-2 text-[0.65rem] text-ink-subtle">
        <span>latency {diagnosis.execution.latency_ms} ms · attempts {diagnosis.execution.attempts}</span>
        <span>
          context{" "}
          {diagnosis.context_timestamp
            ? new Date(diagnosis.context_timestamp).toLocaleString()
            : "unavailable"}
        </span>
      </CardFooter>
    </Card>
  );
}

const PRIORITY_RANK: Record<string, number> = {
  immediate: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function LikelihoodBadge({ likelihood }: { likelihood: string }) {
  const tone =
    likelihood === "high"
      ? "border-[color:color-mix(in_oklab,var(--color-critical)_42%,transparent)] text-[color:var(--color-critical)]"
      : likelihood === "medium"
        ? "border-[color:color-mix(in_oklab,var(--color-attention)_42%,transparent)] text-[color:var(--color-attention)]"
        : "border-line text-ink-subtle";
  return (
    <span className={cn("rounded border px-1.5 py-0.5 text-[0.62rem] uppercase tracking-wider", tone)}>
      {likelihood}
    </span>
  );
}

function Citations({
  citations,
  citedIndexes,
}: {
  citations: DiagnosisResponse["diagnosis"]["citations"];
  citedIndexes: readonly number[];
}) {
  return (
    <section aria-labelledby="diagnosis-citations">
      <h3 id="diagnosis-citations" className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
        Sources ({citations.length})
      </h3>
      <ol className="space-y-1.5">
        {citations.map((citation) => {
          const referenced = citedIndexes.includes(citation.index);
          return (
            <li
              key={citation.chunk_id}
              className={cn(
                "flex gap-2.5 rounded-lg border px-3 py-2",
                referenced
                  ? "border-line bg-surface-2"
                  : "border-dashed border-line bg-transparent",
              )}
            >
              <Quote className="mt-0.5 size-3 shrink-0 text-ink-subtle" aria-hidden />
              <div className="min-w-0 flex-1 text-xs">
                <p className="truncate text-ink">
                  [{citation.index}] {citation.title}
                  {citation.section_title ? ` — ${citation.section_title}` : ""}
                </p>
                <p className="mt-0.5 text-ink-subtle">
                  {citation.source_filename ?? "unknown file"}
                  {citation.page_start !== null
                    ? ` · p.${citation.page_start}${citation.page_end && citation.page_end !== citation.page_start ? `–${citation.page_end}` : ""}`
                    : ""}
                  {` · v${citation.document_version}`}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { Bot, History as HistoryIcon, Filter } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SelectMenu } from "@/components/ui/select-menu";
import { Pagination } from "@/components/ui/pagination";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, InlineAlert } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthStatusBadge, SeverityBadge } from "@/components/health/health-visuals";
import { formatTimestamp } from "@/components/health/health-summary-panel";
import { useAgentHistory, useHealthHistory } from "@/hooks/use-vehicle-data";
import { cn } from "@/lib/utils";
import type { AgentDiagnosisItem, Severity } from "@/types/api";

const PAGE_SIZE = 20;

/**
 * History: health snapshots and AI diagnoses over time.
 *
 * The backend paginates these endpoints without server-side filters, so the
 * filters below narrow the current page and say so explicitly rather than
 * pretending to filter the whole archive.
 */
export function VehicleHistoryView() {
  return (
    <Tabs defaultValue="health">
      <TabsList>
        <TabsTrigger value="health">
          <HistoryIcon aria-hidden />
          Health snapshots
        </TabsTrigger>
        <TabsTrigger value="diagnoses">
          <Bot aria-hidden />
          AI diagnoses
        </TabsTrigger>
      </TabsList>

      <TabsContent value="health">
        <HealthHistoryList />
      </TabsContent>
      <TabsContent value="diagnoses">
        <DiagnosisHistoryList />
      </TabsContent>
    </Tabs>
  );
}

function HealthHistoryList() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";
  const [page, setPage] = React.useState(1);
  const [statusFilter, setStatusFilter] = React.useState("all");
  const query = useHealthHistory(vehicleId, page);

  const items = React.useMemo(() => query.data?.items ?? [], [query.data?.items]);
  const filtered = React.useMemo(
    () =>
      statusFilter === "all"
        ? items
        : items.filter((item) => item.health_status === statusFilter),
    [items, statusFilter],
  );

  const statusOptions = [
    { value: "all", label: "All statuses" },
    { value: "critical", label: "Critical" },
    { value: "attention", label: "Needs attention" },
    { value: "healthy", label: "Healthy" },
    { value: "unknown", label: "Unknown" },
  ];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Health snapshots</CardTitle>
          <CardDescription>
            Every stored analysis, newest first
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Filter className="size-3.5 text-ink-subtle" aria-hidden />
          <div className="w-40">
            <SelectMenu
              value={statusFilter}
              options={statusOptions}
              onChange={setStatusFilter}
              label="Filter by status"
              triggerClassName="h-8 py-0 text-xs"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {query.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : query.isError ? (
          <ErrorState
            error={query.error}
            className="m-4"
            onRetry={() => query.refetch()}
          />
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No health snapshots yet"
              description="Snapshots are created whenever the health analysis runs. Use Analyze health to create the first one."
            />
          </div>
        ) : (
          <>
            {statusFilter !== "all" && filtered.length === 0 ? (
              <div className="px-4 pt-4">
                <InlineAlert tone="info">
                  No snapshots on this page match “{statusFilter}”. Change the filter or
                  turn the page.
                </InlineAlert>
              </div>
            ) : null}
            <div className="w-full overflow-x-auto scrollbar-slim">
              <table className="w-full min-w-[44rem] text-left">
                <caption className="sr-only">
                  Health snapshots for this vehicle, newest first
                </caption>
                <thead>
                  <tr className="border-b border-line">
                    <Th>Generated</Th>
                    <Th align="right">Score</Th>
                    <Th>Status</Th>
                    <Th align="right">Samples</Th>
                    <Th align="right">Confidence</Th>
                    <Th>Window</Th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((snapshot) => (
                    <tr
                      key={snapshot.id}
                      className="border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2"
                    >
                      <td className="tabular whitespace-nowrap px-4 py-2.5 text-xs text-ink">
                        {formatTimestamp(snapshot.generated_at)}
                      </td>
                      <td className="tabular px-4 py-2.5 text-right text-xs text-ink">
                        {snapshot.health_score === null
                          ? "—"
                          : snapshot.health_score.toFixed(0)}
                      </td>
                      <td className="px-4 py-2.5">
                        <HealthStatusBadge status={snapshot.health_status} size="sm" />
                      </td>
                      <td className="tabular px-4 py-2.5 text-right text-xs text-ink-muted">
                        {snapshot.sample_count}
                      </td>
                      <td className="tabular px-4 py-2.5 text-right text-xs text-ink-muted">
                        {snapshot.confidence === null
                          ? "—"
                          : `${(snapshot.confidence * 100).toFixed(0)}%`}
                      </td>
                      <td className="tabular whitespace-nowrap px-4 py-2.5 text-xs text-ink-subtle">
                        {formatTimestamp(snapshot.window_start)} →{" "}
                        {formatTimestamp(snapshot.window_end)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={query.data?.page ?? page}
              pageSize={query.data?.page_size ?? PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              label="Health snapshots"
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function DiagnosisHistoryList() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";
  const [page, setPage] = React.useState(1);
  const [severity, setSeverity] = React.useState("all");
  const [status, setStatus] = React.useState("all");
  const [trigger, setTrigger] = React.useState("all");
  const query = useAgentHistory(vehicleId, page);

  const items = React.useMemo(() => query.data?.items ?? [], [query.data?.items]);

  // Statuses and triggers are discovered from the data rather than hard-coded.
  const statuses = React.useMemo(
    () => uniqueValues(items.map((item) => item.status)),
    [items],
  );
  const triggers = React.useMemo(
    () => uniqueValues(items.map((item) => item.trigger_type)),
    [items],
  );

  const filtered = React.useMemo(
    () =>
      items.filter(
        (item) =>
          (severity === "all" || item.severity === severity) &&
          (status === "all" || item.status === status) &&
          (trigger === "all" || item.trigger_type === trigger),
      ),
    [items, severity, status, trigger],
  );

  const hasFilters = severity !== "all" || status !== "all" || trigger !== "all";

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>AI diagnoses</CardTitle>
          <CardDescription>
            Persisted agent runs, including failures and fallbacks
          </CardDescription>
        </div>
      </CardHeader>

      <div className="flex flex-wrap items-end gap-2 border-b border-line px-4 py-3 sm:px-5">
        <div className="w-36">
          <SelectMenu
            value={severity}
            options={[
              { value: "all", label: "Any severity" },
              { value: "critical", label: "Critical" },
              { value: "warning", label: "Warning" },
              { value: "info", label: "Info" },
            ]}
            onChange={setSeverity}
            label="Filter by severity"
            triggerClassName="h-8 py-0 text-xs"
          />
        </div>
        <div className="w-36">
          <SelectMenu
            value={status}
            options={[
              { value: "all", label: "Any status" },
              ...statuses.map((item) => ({ value: item, label: item })),
            ]}
            onChange={setStatus}
            label="Filter by status"
            triggerClassName="h-8 py-0 text-xs"
          />
        </div>
        <div className="w-44">
          <SelectMenu
            value={trigger}
            options={[
              { value: "all", label: "Any trigger" },
              ...triggers.map((item) => ({ value: item, label: item.replace(/_/g, " ") })),
            ]}
            onChange={setTrigger}
            label="Filter by trigger"
            triggerClassName="h-8 py-0 text-xs"
          />
        </div>
        {hasFilters ? (
          <button
            type="button"
            onClick={() => {
              setSeverity("all");
              setStatus("all");
              setTrigger("all");
            }}
            className="rounded text-xs text-signal-400 underline-offset-4 hover:underline"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      <CardContent className="p-0">
        {query.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : query.isError ? (
          <ErrorState
            error={query.error}
            className="m-4"
            onRetry={() => query.refetch()}
          />
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Bot className="size-5" aria-hidden />}
              title="No diagnoses yet"
              description="Diagnoses are created when you ask a question or when the backend triggers a critical event."
            />
          </div>
        ) : (
          <>
            {hasFilters ? (
              <div className="px-4 pt-4">
                <InlineAlert tone="info">
                  Filters apply to the {items.length} record
                  {items.length === 1 ? "" : "s"} on this page —{" "}
                  {query.data?.total ?? items.length} in total. The API paginates
                  without server-side filters.
                </InlineAlert>
              </div>
            ) : null}

            {hasFilters && filtered.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="Nothing matches these filters"
                  description="Clear the filters or turn to another page."
                />
              </div>
            ) : (
              <ul className="divide-y divide-[color:var(--line)]">
                {filtered.map((item) => (
                  <DiagnosisRow key={item.id} item={item} />
                ))}
              </ul>
            )}

            <Pagination
              page={query.data?.page ?? page}
              pageSize={query.data?.page_size ?? PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              label="AI diagnoses"
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function DiagnosisRow({ item }: { item: AgentDiagnosisItem }) {
  const failed = item.status !== "completed" && item.status !== "success";
  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-xs transition-colors hover:bg-surface-2 sm:px-5",
        failed && "bg-[color:color-mix(in_oklab,var(--color-critical)_6%,transparent)]",
      )}
    >
      <SeverityBadge severity={item.severity as Severity} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-ink">{item.trigger_type.replace(/_/g, " ")}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.65rem] text-ink-subtle">
          <span className="tabular">{formatTimestamp(item.created_at)}</span>
          {item.provider ? <span>· {item.provider}</span> : null}
          {item.model ? <span>· {item.model}</span> : null}
          {item.latency_ms !== null ? <span>· {item.latency_ms} ms</span> : null}
          {item.rag_used ? <span>· {item.rag_evidence_count} docs</span> : null}
          {item.error_code ? (
            <span className="text-[color:var(--color-critical)]">· {item.error_code}</span>
          ) : null}
        </p>
      </div>
      <div className="flex items-center gap-1.5">
        {item.fallback_used ? (
          <Badge tone="attention" size="sm">
            fallback
          </Badge>
        ) : null}
        <Badge tone={failed ? "critical" : "healthy"} size="sm">
          {item.status}
        </Badge>
        {item.confidence !== null ? (
          <span className="tabular w-10 text-right text-[0.65rem] text-ink-subtle">
            {(item.confidence * 100).toFixed(0)}%
          </span>
        ) : null}
      </div>
    </li>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      scope="col"
      className={cn(
        "px-4 py-2.5 text-[0.68rem] font-medium uppercase tracking-wider text-ink-subtle",
        align === "right" ? "text-right" : "text-left",
      )}
    >
      {children}
    </th>
  );
}

function uniqueValues(values: readonly string[]): string[] {
  return Array.from(new Set(values)).sort();
}

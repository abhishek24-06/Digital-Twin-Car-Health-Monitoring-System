"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import {
  Bell,
  CheckCircle2,
  ChevronRight,
  Clock,
  Info,
  ListChecks,
  ShieldAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl, type SelectOption } from "@/components/ui/select-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/states/feedback";
import { SEVERITY_ICON, SeverityBadge } from "@/components/health/health-visuals";
import { useAlertDetail, useVehicleAlerts } from "@/hooks/use-vehicle-data";
import { useAcknowledgeAlert, useResolveAlert } from "@/hooks/use-mutations";
import { useSessionStore } from "@/lib/session-store";
import { formatDateTime, formatMetricValue } from "@/lib/format";
import { metricLabel } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import type { AlertDetail, AlertEventItem, AlertItem, AlertStatus } from "@/types/api";

const PAGE_SIZE = 20;

type StatusFilter = "all" | AlertStatus;
type SeverityFilter = "all" | "warning" | "critical";

const STATUS_FILTER_OPTIONS: ReadonlyArray<SelectOption<StatusFilter>> = [
  { value: "all", label: "All", description: "Every alert regardless of status" },
  { value: "open", label: "Open", description: "Not yet acknowledged" },
  { value: "acknowledged", label: "Acknowledged", description: "Being handled" },
  { value: "resolved", label: "Resolved", description: "Closed" },
];

const SEVERITY_FILTER_OPTIONS: ReadonlyArray<SelectOption<SeverityFilter>> = [
  { value: "all", label: "Any severity" },
  { value: "warning", label: "Warning" },
  { value: "critical", label: "Critical" },
];

const STATUS_TONE: Record<AlertStatus, "critical" | "accent" | "healthy"> = {
  open: "critical",
  acknowledged: "accent",
  resolved: "healthy",
};

const EVENT_LABEL: Record<string, string> = {
  created: "Created",
  recurred: "Recurred",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

/**
 * Alerts tab: the persistent, vehicle-scoped alert records produced from the
 * current session. Findings inside a snapshot are immutable evidence; an alert
 * is the mutable record that carries a lifecycle (open → acknowledged →
 * resolved) and a permanent audit trail. Historical windowed analyses never
 * create alerts, and a resolved alert is never reopened — a recurrence creates
 * a new one.
 */
export function VehicleAlertsView() {
  const params = useParams<{ id: string }>();
  const vehicleId = typeof params?.id === "string" ? params.id : "";

  const [status, setStatus] = React.useState<StatusFilter>("all");
  const [severity, setSeverity] = React.useState<SeverityFilter>("all");
  const [page, setPage] = React.useState(1);
  const [selectedAlertId, setSelectedAlertId] = React.useState<string | null>(null);

  const query = useVehicleAlerts(vehicleId, {
    status: status === "all" ? undefined : status,
    severity: severity === "all" ? undefined : severity,
    page,
  });

  const acknowledge = useAcknowledgeAlert(vehicleId);
  const resolve = useResolveAlert(vehicleId);
  const mutationError = acknowledge.error ?? resolve.error;

  const items = query.data?.items ?? [];
  const hasFilters = status !== "all" || severity !== "all";
  const busy = acknowledge.isPending || resolve.isPending;

  const changeStatus = (next: StatusFilter) => {
    setStatus(next);
    setPage(1);
  };
  const changeSeverity = (next: SeverityFilter) => {
    setSeverity(next);
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-signal-400">
              <Bell className="size-4" aria-hidden />
            </span>
            <div>
              <CardTitle>Alerts</CardTitle>
              <CardDescription>
                Persistent records from the current session, kept separate from
                historical analysis. Acknowledge to take ownership, resolve to
                close — every transition is recorded and a resolved alert is never
                reopened.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap items-start gap-4">
          <div>
            <p className="mb-1 text-[0.62rem] uppercase tracking-wider text-ink-subtle">
              Status
            </p>
            <SegmentedControl
              value={status}
              options={STATUS_FILTER_OPTIONS}
              onChange={changeStatus}
              ariaLabel="Filter alerts by status"
            />
          </div>
          <div>
            <p className="mb-1 text-[0.62rem] uppercase tracking-wider text-ink-subtle">
              Severity
            </p>
            <SegmentedControl
              value={severity}
              options={SEVERITY_FILTER_OPTIONS}
              onChange={changeSeverity}
              ariaLabel="Filter alerts by severity"
            />
          </div>
        </CardContent>
      </Card>

      {mutationError ? <ErrorState error={mutationError} compact /> : null}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Alert log</CardTitle>
            <CardDescription>
              Most severe first, newest observation breaking ties
            </CardDescription>
          </div>
          {query.data ? (
            <Badge tone="neutral" size="sm">
              {query.data.total.toLocaleString()} total
            </Badge>
          ) : null}
        </CardHeader>

        <CardContent className="p-0">
          {query.isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-16 w-full" />
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
                icon={
                  hasFilters ? (
                    <ListChecks className="size-5" aria-hidden />
                  ) : (
                    <ShieldAlert className="size-5" aria-hidden />
                  )
                }
                title={hasFilters ? "No alerts match these filters" : "No alerts"}
                description={
                  hasFilters
                    ? "No persisted alerts match the selected status and severity. Clear a filter to widen the search."
                    : "Alerts appear when a current-session health evaluation raises a warning or critical finding. A stopped session produces no alerts."
                }
              />
            </div>
          ) : (
            <>
              <ul className="divide-y divide-[color:var(--line)]">
                {items.map((alert) => (
                  <AlertRow
                    key={alert.id}
                    alert={alert}
                    busy={busy}
                    onOpen={() => setSelectedAlertId(alert.id)}
                    onAcknowledge={() => acknowledge.mutate({ alertId: alert.id })}
                    onResolve={() => resolve.mutate({ alertId: alert.id })}
                  />
                ))}
              </ul>
              <Pagination
                page={query.data?.page ?? page}
                pageSize={query.data?.page_size ?? PAGE_SIZE}
                total={query.data?.total ?? 0}
                onPageChange={setPage}
                label="Alerts"
              />
            </>
          )}
        </CardContent>
      </Card>

      <AlertDetailDialog
        vehicleId={vehicleId}
        alertId={selectedAlertId}
        onOpenChange={(open) => {
          if (!open) setSelectedAlertId(null);
        }}
      />
    </div>
  );
}

function AlertRow({
  alert,
  busy,
  onOpen,
  onAcknowledge,
  onResolve,
}: {
  alert: AlertItem;
  busy: boolean;
  onOpen: () => void;
  onAcknowledge: () => void;
  onResolve: () => void;
}) {
  const Icon = SEVERITY_ICON[alert.severity];
  const resolved = alert.status === "resolved";

  return (
    <li className="flex flex-wrap items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-2 sm:px-5">
      <Icon
        className={
          alert.severity === "critical"
            ? "mt-0.5 size-4 shrink-0 text-[color:var(--color-critical)]"
            : "mt-0.5 size-4 shrink-0 text-[color:var(--color-attention)]"
        }
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={alert.severity} />
          <Badge tone={STATUS_TONE[alert.status]} size="sm">
            {alert.status}
          </Badge>
          {alert.provisional ? (
            <Badge tone="unknown" size="sm">
              provisional
            </Badge>
          ) : null}
          {alert.occurrence_count > 1 ? (
            <Badge tone="neutral" size="sm">
              ×{alert.occurrence_count}
            </Badge>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="mt-1 block max-w-full text-left text-sm font-medium text-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400"
        >
          {alert.title}
        </button>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{alert.message}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.65rem] text-ink-subtle">
          <span className="font-mono">{alert.rule_id}</span>
          {alert.category ? <span>· {alert.category}</span> : null}
          {alert.metric ? <span>· {metricLabel(alert.metric)}</span> : null}
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" aria-hidden />· seen{" "}
            {formatDateTime(alert.first_seen_at)} → {formatDateTime(alert.last_seen_at)}
          </span>
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {alert.status === "open" ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={onAcknowledge}>
            <Bell aria-hidden />
            Acknowledge
          </Button>
        ) : null}
        {!resolved ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={onResolve}>
            <CheckCircle2 aria-hidden />
            Resolve
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={onOpen}>
          Details
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </li>
  );
}

function AlertDetailDialog({
  vehicleId,
  alertId,
  onOpenChange,
}: {
  vehicleId: string;
  alertId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const detail = useAlertDetail(vehicleId, alertId);
  const alert = detail.data ?? null;

  return (
    <Dialog open={Boolean(alertId)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        {detail.isPending && alertId ? (
          <DialogBody className="space-y-3">
            <Skeleton className="h-5 w-64" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-32 w-full" />
          </DialogBody>
        ) : detail.isError ? (
          <DialogBody>
            <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
          </DialogBody>
        ) : alert ? (
          <AlertEditor
            key={alert.id}
            vehicleId={vehicleId}
            alert={alert}
            onClose={() => onOpenChange(false)}
          />
        ) : (
          <DialogBody />
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Keyed by alert id so opening a different alert remounts fresh note/mutation
 * state. The detail query is bypassed after an action: the mutation result is
 * written into the same cache entry, so this re-renders with the new status.
 */
function AlertEditor({
  vehicleId,
  alert,
  onClose,
}: {
  vehicleId: string;
  alert: AlertDetail;
  onClose: () => void;
}) {
  const acknowledge = useAcknowledgeAlert(vehicleId);
  const resolve = useResolveAlert(vehicleId);
  const [note, setNote] = React.useState("");
  const actionError = acknowledge.error ?? resolve.error;

  return (
    <>
      <DialogHeader>
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={alert.severity} />
          <Badge tone={STATUS_TONE[alert.status]} size="sm">
            {alert.status}
          </Badge>
          {alert.provisional ? (
            <Badge tone="unknown" size="sm">
              provisional
            </Badge>
          ) : null}
        </div>
        <DialogTitle className="mt-1">{alert.title}</DialogTitle>
        <DialogDescription>{alert.message}</DialogDescription>
      </DialogHeader>

      <DialogBody className="space-y-4">
        {actionError ? <ErrorState error={actionError} compact /> : null}

        <AlertFacts alert={alert} />

        <EvidenceBlock evidence={alert.evidence} />

        <section>
          <h3 className="mb-2 text-[0.68rem] font-semibold uppercase tracking-wider text-ink-subtle">
            Audit history
          </h3>
          <AlertTimeline events={alert.events} />
        </section>

        {alert.status !== "resolved" ? (
          <label className="block">
            <span className="mb-1 block text-[0.62rem] uppercase tracking-wider text-ink-subtle">
              Note (optional, recorded in the audit history)
            </span>
            <Textarea
              value={note}
              rows={2}
              maxLength={2000}
              placeholder="Add context for the next reader…"
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
        ) : null}
      </DialogBody>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
        {alert.status === "open" ? (
          <Button
            variant="outline"
            loading={acknowledge.isPending}
            disabled={resolve.isPending}
            onClick={() => acknowledge.mutate({ alertId: alert.id, note })}
          >
            Acknowledge
          </Button>
        ) : null}
        {alert.status !== "resolved" ? (
          <Button
            loading={resolve.isPending}
            disabled={acknowledge.isPending}
            onClick={() => resolve.mutate({ alertId: alert.id, note })}
          >
            Resolve
          </Button>
        ) : null}
      </DialogFooter>
    </>
  );
}

function AlertFacts({ alert }: { alert: AlertDetail }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs sm:grid-cols-3">
      <Fact label="Rule" value={alert.rule_id} mono />
      <Fact label="Category" value={alert.category ?? "—"} />
      <Fact label="Occurrences" value={String(alert.occurrence_count)} />
      <Fact
        label="Observed"
        value={withUnit(alert.observed_value, alert.unit)}
      />
      <Fact label="Threshold" value={withUnit(alert.threshold, alert.unit)} />
      <Fact
        label="Confidence"
        value={
          alert.confidence === null ? "—" : `${(alert.confidence * 100).toFixed(0)}%`
        }
      />
      <Fact label="First seen" value={formatDateTime(alert.first_seen_at)} />
      <Fact label="Last seen" value={formatDateTime(alert.last_seen_at)} />
      <Fact
        label="Run"
        value={alert.simulation_run_id ?? "current session"}
        mono={Boolean(alert.simulation_run_id)}
      />
      {alert.acknowledged_at ? (
        <Fact label="Acknowledged" value={formatDateTime(alert.acknowledged_at)} />
      ) : null}
      {alert.acknowledge_note ? (
        <Fact label="Ack note" value={alert.acknowledge_note} />
      ) : null}
      {alert.resolved_at ? (
        <Fact label="Resolved" value={formatDateTime(alert.resolved_at)} />
      ) : null}
      {alert.resolution_note ? (
        <Fact label="Resolve note" value={alert.resolution_note} />
      ) : null}
    </dl>
  );
}

function Fact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.62rem] uppercase tracking-wider text-ink-subtle">{label}</dt>
      <dd className={cn("mt-0.5 break-words text-ink", mono && "font-mono text-[0.68rem]")}>
        {value}
      </dd>
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence: Record<string, unknown> | null }) {
  const entries = Object.entries(evidence ?? {});
  if (entries.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
        <Info className="size-3.5" aria-hidden />
        No additional evidence recorded for this alert.
      </p>
    );
  }
  return (
    <section>
      <h3 className="mb-2 text-[0.68rem] font-semibold uppercase tracking-wider text-ink-subtle">
        Evidence
      </h3>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-xs sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0">
            <dt className="font-mono text-[0.65rem] text-ink-subtle">{key}</dt>
            <dd className="tabular mt-0.5 break-words text-ink">
              {formatEvidenceValue(value)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function AlertTimeline({ events }: { events: AlertEventItem[] }) {
  const currentUserId = useSessionStore((state) => state.user?.id ?? null);

  if (events.length === 0) {
    return <p className="text-xs text-ink-subtle">No transitions recorded yet.</p>;
  }

  return (
    <ul className="space-y-1.5">
      {events.map((event) => (
        <li
          key={event.id}
          className="flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs"
        >
          <span className="font-medium text-ink">
            {EVENT_LABEL[event.event_type] ?? event.event_type}
          </span>
          {event.from_status || event.to_status ? (
            <span className="text-[0.65rem] uppercase tracking-wider text-ink-subtle">
              {event.from_status ?? "—"} → {event.to_status ?? "—"}
            </span>
          ) : null}
          <span className="text-[0.65rem] text-ink-subtle">
            {actorLabel(event, currentUserId)}
          </span>
          <span className="tabular ml-auto text-[0.65rem] text-ink-subtle">
            {formatDateTime(event.created_at)}
          </span>
          {event.note ? (
            <span className="w-full text-ink-muted">“{event.note}”</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function actorLabel(event: AlertEventItem, currentUserId: string | null): string {
  if (event.actor_user_id === null) return "System";
  if (currentUserId && event.actor_user_id === currentUserId) return "You";
  return "Another user";
}

function withUnit(value: number | null, unit: string | null): string {
  if (value === null) return "—";
  const formatted = formatMetricValue(value, unit ?? undefined);
  return unit ? `${formatted} ${unit}` : formatted;
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

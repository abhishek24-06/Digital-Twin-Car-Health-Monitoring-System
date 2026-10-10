"use client";

import * as React from "react";
import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useWorkflowAllEvents,
  useWorkflowConnection,
} from "@/components/workflow/workflow-stream-provider";
import { WorkflowConnectionIndicator } from "./pipeline";
import { WorkflowStatusBadge, type StageStatus } from "./status";
import { useWorkflowStatus } from "@/hooks/use-workflow";
import { EventTimeline } from "./event-timeline";
import { PipelineTelemetry } from "./pipeline-telemetry";
import { PipelineRAGIngestion } from "./pipeline-rag-ingestion";
import { PipelineRAGQuery } from "./pipeline-rag-query";
import { PipelineHealth } from "./pipeline-health";
import { PipelineAgent } from "./pipeline-agent";
import { Filters } from "./filters";
import { Overview } from "./overview";
import type { WorkflowEventFilters, WorkflowEventResponse } from "@/types/api";

type Tab =
  | "overview"
  | "telemetry"
  | "rag-ingestion"
  | "rag-query"
  | "health"
  | "agent"
  | "simulation"
  | "system";

const DEFAULT_FILTERS: WorkflowEventFilters = { limit: 100, offset: 0 };

export function WorkflowView() {
  const [activeTab, setActiveTab] = React.useState<Tab>("overview");
  const [paused, setPaused] = React.useState(false);
  const [frozen, setFrozen] = React.useState<WorkflowEventResponse[] | null>(null);
  const [clearedAt, setClearedAt] = React.useState<number | null>(null);
  const [filters, setFilters] = React.useState<WorkflowEventFilters>(DEFAULT_FILTERS);

  const liveEvents = useWorkflowAllEvents();
  const connection = useWorkflowConnection();
  const { status: workflowStatus } = useWorkflowStatus();

  // Pausing the Monitor freezes only this view; the shared stream keeps flowing
  // to the rest of the app.
  const baseEvents = React.useMemo<readonly WorkflowEventResponse[]>(
    () => (paused ? (frozen ?? []) : liveEvents),
    [paused, frozen, liveEvents],
  );

  const filteredEvents = React.useMemo(() => {
    let list = [...baseEvents];
    if (clearedAt !== null) {
      list = list.filter(
        (event) => new Date(event.timestamp).getTime() > clearedAt,
      );
    }
    if (filters.workflow) list = list.filter((e) => e.workflow === filters.workflow);
    if (filters.status) list = list.filter((e) => e.status === filters.status);
    if (filters.vehicle_id) list = list.filter((e) => e.vehicle_id === filters.vehicle_id);
    if (filters.document_id) list = list.filter((e) => e.document_id === filters.document_id);
    if (filters.correlation_id) {
      list = list.filter((e) => e.correlation_id === filters.correlation_id);
    }
    return list;
  }, [baseEvents, clearedAt, filters]);

  const overviewConnection =
    connection === "live"
      ? "live"
      : connection === "disconnected"
        ? "offline"
        : "reconnecting";

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "Overview", icon: <GitBranch className="size-4" /> },
    { id: "telemetry", label: "Telemetry", icon: <GitBranch className="size-4" /> },
    { id: "rag-ingestion", label: "RAG Ingestion", icon: <GitBranch className="size-4" /> },
    { id: "rag-query", label: "RAG Query", icon: <GitBranch className="size-4" /> },
    { id: "health", label: "Health", icon: <GitBranch className="size-4" /> },
    { id: "agent", label: "Agent", icon: <GitBranch className="size-4" /> },
    { id: "simulation", label: "Simulation", icon: <GitBranch className="size-4" /> },
    { id: "system", label: "System", icon: <GitBranch className="size-4" /> },
  ];

  const togglePause = () => {
    if (paused) {
      setFrozen(null);
      setPaused(false);
    } else {
      setFrozen([...liveEvents]);
      setPaused(true);
    }
  };

  const clearEvents = () => setClearedAt(Date.now());

  const exportEvents = () => {
    const blob = new Blob([JSON.stringify(filteredEvents, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `workflow-events-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-line">
        <div className="flex items-center gap-4">
          <GitBranch className="size-6 text-signal-400" />
          <div>
            <h1 className="text-xl font-semibold text-ink">System Workflow</h1>
            <p className="text-sm text-ink-muted">
              Real-time view of the Digital Twin execution pipeline
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <WorkflowConnectionIndicator status={connection} />

          <button
            onClick={togglePause}
            className={cn(
              "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
              paused
                ? "bg-surface-3 text-ink-muted hover:bg-surface-2"
                : "bg-signal-100 text-signal-600 hover:bg-signal-200",
            )}
          >
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </header>

      {/* Filters */}
      <Filters
        events={liveEvents as WorkflowEventResponse[]}
        filters={filters}
        onFilterChange={setFilters}
        onClear={() => setFilters(DEFAULT_FILTERS)}
      />

      {/* Tab navigation */}
      <nav className="flex flex-wrap gap-1 px-4 pb-4" role="tablist" aria-label="Workflow pipelines">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
              activeTab === tab.id
                ? "bg-surface-3 text-ink shadow-[var(--shadow-panel)]"
                : "text-ink-muted hover:bg-surface-2 hover:text-ink",
            )}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <main className="flex-1 overflow-auto p-4">
        {activeTab === "overview" && (
          <Overview
            workflowStatus={workflowStatus}
            connectionStatus={overviewConnection}
            totalEvents={liveEvents.length}
            _isLoading={false}
          />
        )}

        {activeTab === "telemetry" && (
          <PipelineTelemetry events={filteredEvents} workflowStatus={workflowStatus} />
        )}

        {activeTab === "rag-ingestion" && (
          <PipelineRAGIngestion events={filteredEvents} />
        )}

        {activeTab === "rag-query" && (
          <PipelineRAGQuery events={filteredEvents} />
        )}

        {activeTab === "health" && (
          <PipelineHealth events={filteredEvents} workflowStatus={workflowStatus} />
        )}

        {activeTab === "agent" && (
          <PipelineAgent events={filteredEvents} />
        )}

        {activeTab === "simulation" && (
          <WorkflowEventList
            title="Simulation events"
            events={filteredEvents.filter((e) => e.workflow === "simulation")}
          />
        )}

        {activeTab === "system" && (
          <WorkflowEventList
            title="System events"
            events={filteredEvents.filter((e) => e.workflow === "system")}
          />
        )}
      </main>

      {/* Event timeline at bottom */}
      <div className="border-t border-line">
        <EventTimeline
          events={filteredEvents}
          total={filteredEvents.length}
          isLoading={false}
          onExport={exportEvents}
          onClear={clearEvents}
        />
      </div>
    </div>
  );
}

function WorkflowEventList({
  title,
  events,
}: {
  title: string;
  events: WorkflowEventResponse[];
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {events.length === 0 ? (
        <p className="text-sm text-ink-muted">No events observed yet.</p>
      ) : (
        <ul className="space-y-1">
          {events.map((event) => (
            <li
              key={event.event_id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-1 px-3 py-2 text-sm"
            >
              <WorkflowStatusBadge status={event.status as StageStatus} />
              <span className="font-mono text-xs text-ink-muted">{event.stage}</span>
              <span className="text-ink">{event.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

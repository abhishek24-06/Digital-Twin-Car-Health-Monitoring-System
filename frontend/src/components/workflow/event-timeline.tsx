"use client";

import * as React from "react";
import {
  Filter,
  Trash2,
  Search,
  ChevronDown,
  ChevronUp,
  Download,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowEventResponse, WorkflowType, WorkflowStatus } from "@/types/api";

interface EventTimelineProps {
  events: WorkflowEventResponse[];
  total: number;
  isLoading: boolean;
  loadMore?: () => Promise<void>;
  onExport?: () => void;
  onClear?: () => void;
}

const WORKFLOW_COLORS: Record<WorkflowType, string> = {
  telemetry: "bg-blue-500",
  rag_ingestion: "bg-purple-500",
  rag_query: "bg-violet-500",
  health: "bg-green-500",
  agent: "bg-orange-500",
  simulation: "bg-gray-500",
  system: "bg-slate-500",
};

const STATUS_COLORS: Record<WorkflowStatus, string> = {
  started: "bg-blue-500",
  running: "bg-yellow-500",
  success: "bg-green-500",
  warning: "bg-orange-500",
  degraded: "bg-amber-500",
  skipped: "bg-slate-400",
  error: "bg-red-500",
};

function EventTimeline({ events, total, isLoading, loadMore, onExport, onClear }: EventTimelineProps) {
  const [searchQuery, setSearchQuery] = React.useState("");
  const [showFilters, setShowFilters] = React.useState(false);

  const filteredEvents = React.useMemo(() => {
    if (!searchQuery) return events;
    const query = searchQuery.toLowerCase();
    return events.filter(
      (e) =>
        e.message.toLowerCase().includes(query) ||
        e.stage.toLowerCase().includes(query) ||
        (e.vehicle_id?.toLowerCase().includes(query) ?? false) ||
        (e.document_id?.toLowerCase().includes(query) ?? false) ||
        (e.correlation_id?.toLowerCase().includes(query) ?? false)
    );
  }, [events, searchQuery]);

  return (
    <div className="border-t border-line bg-surface-1">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 p-4 border-b border-line">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <label className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-ink-subtle" />
            <input
              type="text"
              placeholder="Search events (stage, message, vehicle, document)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 text-sm bg-surface-2 border border-line rounded-lg text-ink placeholder:text-ink-subtle focus:outline-none focus:ring-2 focus:ring-signal-400"
            />
          </label>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={cn(
              "flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors",
              showFilters && "bg-signal-100 border-signal-300 text-signal-600",
              "bg-surface-2 border-line text-ink hover:bg-surface-3",
            )}
          >
            <Filter className="size-4" />
            <span>Filters</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          {loadMore ? (
            <button
              onClick={loadMore}
              disabled={isLoading}
              className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border bg-surface-2 border-line text-ink hover:bg-surface-3 disabled:opacity-50"
            >
              <span>Load More</span>
              <span className="text-xs text-ink-subtle">({filteredEvents.length}/{total})</span>
            </button>
          ) : null}
          <button
            onClick={onExport}
            className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border bg-surface-2 border-line text-ink hover:bg-surface-3"
          >
            <Download className="size-4" />
            <span>Export</span>
          </button>
          <button
            onClick={onClear}
            className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border bg-red-50 border-red-200 text-red-600 hover:bg-red-100"
          >
            <Trash2 className="size-4" />
            <span>Clear</span>
          </button>
        </div>
      </div>

      {/* Advanced Filters */}
      {showFilters && (
        <div className="p-4 border-b border-line bg-surface-1">
          <FiltersPanel onClose={() => setShowFilters(false)} />
        </div>
      )}

      {/* Event List */}
      <div className="max-h-[400px] overflow-y-auto">
        {filteredEvents.length === 0 && !isLoading ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <span className="text-ink-subtle text-lg mb-2">No events found</span>
            <p className="text-sm text-ink-subtle">
              {searchQuery ? "Try adjusting your search or filters" : "Events will appear here as the system runs"}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-line">
            {filteredEvents.map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
            {isLoading && (
              <div className="flex items-center justify-center py-4">
                <span className="animate-spin size-6 border-2 border-signal-400 border-t-transparent rounded-full" />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: WorkflowEventResponse }) {
  const [expanded, setExpanded] = React.useState(false);

  return (
    <div className="p-3 hover:bg-surface-2 transition-colors">
      <div className="flex items-start gap-3">
        <div className="flex flex-col items-center gap-1 min-w-[60px]">
          <div
            className={cn(
              "size-2 rounded-full",
              WORKFLOW_COLORS[event.workflow] || "bg-gray-500",
            )}
            title={event.workflow}
          />
          <span className="text-[10px] text-ink-subtle font-mono">
            {event.workflow}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-ink">{event.stage}</span>
            <span
              className={cn(
                "px-2 py-0.5 text-xs font-medium rounded-full",
                STATUS_COLORS[event.status] || "bg-gray-500",
              )}
            >
              {event.status}
            </span>
            <span className="text-xs text-ink-subtle font-mono">
              {formatRelative(event.timestamp)}
            </span>
          </div>

          <p className="text-sm text-ink mt-1 truncate">{event.message}</p>

          {event.vehicle_id && (
            <div className="flex flex-wrap gap-1 mt-2 text-xs">
              <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded">
                Vehicle: {event.vehicle_id.slice(0, 8)}
              </span>
              {event.document_id && (
                <span className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded">
                  Doc: {event.document_id.slice(0, 8)}
                </span>
              )}
              {event.correlation_id && (
                <span className="px-2 py-0.5 bg-gray-50 text-gray-600 rounded">
                  Corr: {event.correlation_id.slice(0, 8)}
                </span>
              )}
            </div>
          )}

          {event.duration_ms && (
            <div className="mt-2 flex items-center gap-2 text-xs text-ink-subtle">
              <Zap className="size-3" />
              <span>Duration: {event.duration_ms.toFixed(1)}ms</span>
            </div>
          )}

          <div className="mt-2 text-xs text-ink-subtle font-mono">
            Event ID: {event.event_id}
          </div>

          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-2 text-xs text-ink-subtle hover:text-ink flex items-center gap-1"
          >
            {expanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
            {expanded ? "Collapse" : "Expand"} metadata
          </button>

          {expanded && event.metadata && Object.keys(event.metadata).length > 0 && (
            <div className="mt-2 p-3 bg-surface-1 rounded-lg border border-line animate-slide-down">
              <pre className="text-xs text-ink-muted overflow-x-auto max-h-60">
                {JSON.stringify(event.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FiltersPanel({ onClose }: { onClose: () => void }) {
  // This would be a more detailed filter panel - simplified for now
  return (
    <div className="flex flex-wrap items-center gap-4">
      <button onClick={onClose} className="text-sm text-ink-subtle hover:text-ink">
        ← Close filters
      </button>
      <span className="text-sm text-ink-subtle">Advanced filters panel - to be implemented</span>
    </div>
  );
}

function formatRelative(date: string | Date): string {
  const d = new Date(date);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 1000) return "just now";
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

export { EventTimeline };
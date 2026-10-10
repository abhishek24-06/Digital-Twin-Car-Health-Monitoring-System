"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  WorkflowEventResponse,
  WorkflowEventFilters,
  WorkflowType,
  WorkflowStatus,
} from "@/types/api";

interface FiltersProps {
  events: WorkflowEventResponse[];
  filters: WorkflowEventFilters;
  onFilterChange: (filters: WorkflowEventFilters) => void;
  onClear: () => void;
}

/**
 * Functional filter bar for the Workflow Monitor.
 *
 * Every control updates the parent's filter state; the parent applies the
 * filters to the shared event buffer. Nothing here is decorative.
 */
export function Filters({ events, filters, onFilterChange, onClear }: FiltersProps) {
  const [showWorkflow, setShowWorkflow] = React.useState(false);
  const [showStatus, setShowStatus] = React.useState(false);
  const [showVehicle, setShowVehicle] = React.useState(false);
  const [showDocument, setShowDocument] = React.useState(false);

  const update = (patch: Partial<WorkflowEventFilters>) => {
    onFilterChange({ ...filters, ...patch });
  };

  // Extract unique values from events for dropdown options
  const workflows = React.useMemo(() => {
    const types = new Set<WorkflowType>();
    events.forEach((e) => types.add(e.workflow));
    return Array.from(types).sort();
  }, [events]);

  const statuses = React.useMemo(() => {
    const types = new Set<WorkflowStatus>();
    events.forEach((e) => types.add(e.status));
    return Array.from(types).sort();
  }, [events]);

  const vehicles = React.useMemo(() => {
    const ids = new Set<string>();
    events.forEach((e) => e.vehicle_id && ids.add(e.vehicle_id));
    return Array.from(ids).sort();
  }, [events]);

  const documents = React.useMemo(() => {
    const ids = new Set<string>();
    events.forEach((e) => e.document_id && ids.add(e.document_id));
    return Array.from(ids).sort();
  }, [events]);

  return (
    <div className="flex flex-wrap items-center gap-2 p-3 bg-surface-1 border-b border-line">
      <FilterDropdown
        label="Workflow"
        icon={<span className="size-4">&#x2699;</span>}
        options={workflows.map((w) => ({ value: w, label: w }))}
        value={filters.workflow}
        onChange={(v) => update({ workflow: (v as WorkflowType) ?? undefined })}
        isOpen={showWorkflow}
        setIsOpen={setShowWorkflow}
        placeholder="All workflows"
      />

      <FilterDropdown
        label="Status"
        icon={<span className="size-4">&#x2b24;</span>}
        options={statuses.map((s) => ({ value: s, label: s }))}
        value={filters.status}
        onChange={(v) => update({ status: (v as WorkflowStatus) ?? undefined })}
        isOpen={showStatus}
        setIsOpen={setShowStatus}
        placeholder="All statuses"
      />

      <FilterDropdown
        label="Vehicle"
        icon={<span className="size-4">&#x1f697;</span>}
        options={vehicles.map((v) => ({ value: v, label: v.slice(0, 8) }))}
        value={filters.vehicle_id}
        onChange={(v) => update({ vehicle_id: v })}
        isOpen={showVehicle}
        setIsOpen={setShowVehicle}
        placeholder="All vehicles"
      />

      <FilterDropdown
        label="Document"
        icon={<span className="size-4">&#x1f4c4;</span>}
        options={documents.map((d) => ({ value: d, label: d.slice(0, 8) }))}
        value={filters.document_id}
        onChange={(v) => update({ document_id: v })}
        isOpen={showDocument}
        setIsOpen={setShowDocument}
        placeholder="All documents"
      />

      <label className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm">
        <span className="text-ink-muted">Correlation</span>
        <input
          aria-label="Correlation id"
          value={filters.correlation_id ?? ""}
          onChange={(event) =>
            update({ correlation_id: event.target.value || undefined })
          }
          placeholder="correlation id"
          className="w-40 bg-transparent text-ink placeholder:text-ink-subtle focus:outline-none"
        />
      </label>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onClear}
          className="px-3 py-1.5 text-sm rounded-lg border bg-red-50 border-red-200 text-red-600 hover:bg-red-100"
        >
          Clear All
        </button>
      </div>
    </div>
  );
}

interface FilterDropdownProps {
  label: string;
  icon: React.ReactNode;
  options: { value: string; label: string }[];
  value: string | null | undefined;
  onChange: (value: string | undefined) => void;
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  placeholder: string;
}

function FilterDropdown({
  label,
  icon,
  options,
  value,
  onChange,
  isOpen,
  setIsOpen,
  placeholder,
}: FilterDropdownProps) {
  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-label={`Filter by ${label}`}
        className={cn(
          "flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors",
          isOpen || value
            ? "bg-signal-100 border-signal-300 text-signal-600"
            : "bg-surface-2 border-line text-ink hover:bg-surface-3",
        )}
      >
        {icon}
        <span>{value ?? label}</span>
        <ChevronDown className={cn("size-4 transition-transform", isOpen && "rotate-180")} />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 z-20 min-w-[180px] bg-surface-1 border border-line rounded-lg shadow-lg py-1 animate-slide-down">
          <button
            onClick={() => {
              onChange(undefined);
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm hover:bg-surface-2 text-ink-muted"
          >
            {placeholder}
          </button>
          {options.map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                onChange(opt.value);
                setIsOpen(false);
              }}
              className="w-full px-3 py-2 text-left text-sm hover:bg-surface-2 text-ink"
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

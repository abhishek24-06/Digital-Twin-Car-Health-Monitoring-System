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

type FilterKey = "workflow" | "status" | "vehicle" | "document";

/**
 * Functional filter bar for the Workflow Monitor.
 *
 * Every control updates the parent's filter state; the parent applies the
 * filters to the shared event buffer. Nothing here is decorative.
 *
 * Only one menu may be open at a time (`openKey`): opening another control
 * closes the first, so menus can never overlap each other. Each menu dismisses
 * on outside click, on Escape, and on selection, and is positioned relative to
 * its own trigger (`absolute top-full left-0`) on the app's `z-20` tier — the
 * same tier as the sticky top bar — so it clears the tab content without an
 * arbitrary `z-index`.
 */
export function Filters({ events, filters, onFilterChange, onClear }: FiltersProps) {
  const [openKey, setOpenKey] = React.useState<FilterKey | null>(null);

  const setOpen = React.useCallback((key: FilterKey, open: boolean) => {
    setOpenKey((current) => (open ? key : current === key ? null : current));
  }, []);

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
    <div
      data-testid="filter-bar"
      className="flex flex-wrap items-center gap-2 p-3 bg-surface-1 border-b border-line"
    >
      <FilterDropdown
        filterKey="workflow"
        label="Workflow"
        icon={<span className="size-4">&#x2699;</span>}
        options={workflows.map((w) => ({ value: w, label: w }))}
        value={filters.workflow}
        onChange={(v) => update({ workflow: (v as WorkflowType) ?? undefined })}
        isOpen={openKey === "workflow"}
        onOpenChange={setOpen}
        placeholder="All workflows"
      />

      <FilterDropdown
        filterKey="status"
        label="Status"
        icon={<span className="size-4">&#x2b24;</span>}
        options={statuses.map((s) => ({ value: s, label: s }))}
        value={filters.status}
        onChange={(v) => update({ status: (v as WorkflowStatus) ?? undefined })}
        isOpen={openKey === "status"}
        onOpenChange={setOpen}
        placeholder="All statuses"
      />

      <FilterDropdown
        filterKey="vehicle"
        label="Vehicle"
        icon={<span className="size-4">&#x1f697;</span>}
        options={vehicles.map((v) => ({ value: v, label: v.slice(0, 8) }))}
        value={filters.vehicle_id}
        onChange={(v) => update({ vehicle_id: v })}
        isOpen={openKey === "vehicle"}
        onOpenChange={setOpen}
        placeholder="All vehicles"
      />

      <FilterDropdown
        filterKey="document"
        label="Document"
        icon={<span className="size-4">&#x1f4c4;</span>}
        options={documents.map((d) => ({ value: d, label: d.slice(0, 8) }))}
        value={filters.document_id}
        onChange={(v) => update({ document_id: v })}
        isOpen={openKey === "document"}
        onOpenChange={setOpen}
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
          className="w-28 bg-transparent text-ink placeholder:text-ink-subtle focus:outline-none sm:w-40"
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
  filterKey: FilterKey;
  label: string;
  icon: React.ReactNode;
  options: { value: string; label: string }[];
  value: string | null | undefined;
  onChange: (value: string | undefined) => void;
  isOpen: boolean;
  onOpenChange: (key: FilterKey, open: boolean) => void;
  placeholder: string;
}

function FilterDropdown({
  filterKey,
  label,
  icon,
  options,
  value,
  onChange,
  isOpen,
  onOpenChange,
  placeholder,
}: FilterDropdownProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const menuId = React.useId();

  const close = React.useCallback(
    () => onOpenChange(filterKey, false),
    [filterKey, onOpenChange],
  );

  // Dismiss on outside click and on Escape while this menu is open. Because the
  // parent keeps only one menu open, at most one listener pair is ever mounted.
  React.useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, close]);

  const select = (next: string | undefined) => {
    onChange(next);
    close();
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(filterKey, !isOpen)}
        aria-label={`Filter by ${label}`}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        className={cn(
          "flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
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
        <div
          id={menuId}
          data-testid="filter-menu"
          className={cn(
            "absolute left-0 top-full z-20 mt-1 w-max min-w-[12rem]",
            "max-w-[min(18rem,calc(100vw-2rem))]",
            "max-h-72 overflow-y-auto scrollbar-slim",
            "rounded-lg border border-line bg-surface p-1",
            "shadow-[var(--shadow-pop)] animate-fade-rise",
          )}
        >
          <button
            type="button"
            onClick={() => select(undefined)}
            className="block w-full truncate rounded-md px-3 py-2 text-left text-sm text-ink-muted hover:bg-surface-2"
          >
            {placeholder}
          </button>
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              title={opt.label}
              onClick={() => select(opt.value)}
              className="block w-full truncate rounded-md px-3 py-2 text-left text-sm text-ink hover:bg-surface-2"
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { workflowApi, createWorkflowEventSource } from "@/services/workflow";
import type {
  WorkflowEventResponse,
  WorkflowEventFilters,
  WorkflowStatusResponse,
} from "@/types/api";

export type WorkflowConnectionState = "live" | "reconnecting" | "offline";

export interface UseWorkflowEventsOptions {
  enabled?: boolean;
  filters?: WorkflowEventFilters;
  initialLimit?: number;
  reconnectDelay?: number;
}

export interface UseWorkflowEventsReturn {
  events: WorkflowEventResponse[];
  status: WorkflowConnectionState;
  total: number;
  isLoading: boolean;
  error: string | null;
  loadMore: () => Promise<void>;
  setFilters: (filters: WorkflowEventFilters) => void;
  pause: () => void;
  resume: () => void;
  clear: () => void;
  refetch: () => Promise<void>;
}

export function useWorkflowEvents(
  options: UseWorkflowEventsOptions = {},
): UseWorkflowEventsReturn {
  const {
    enabled = true,
    filters: initialFilters,
    initialLimit = 100,
    reconnectDelay = 2000,
  } = options;

  const [events, setEvents] = useState<WorkflowEventResponse[]>([]);
  const [status, setStatus] = useState<WorkflowConnectionState>("offline");
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<WorkflowEventFilters>({
    limit: initialLimit,
    offset: 0,
    ...initialFilters,
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const pausedRef = useRef(false);
  const mountedRef = useRef(true);
  const filtersRef = useRef(filters);
  const connectRef = useRef<() => void>(() => {});

  // Keep filters ref in sync
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  const setFilters = useCallback((newFilters: WorkflowEventFilters) => {
    setFiltersState((prev) => ({ ...prev, ...newFilters, offset: 0 }));
    setEvents([]); // Clear events when filters change
    setTotal(0);
  }, []);

  const pause = useCallback(() => {
    pausedRef.current = true;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setStatus("offline");
  }, []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    if (mountedRef.current) {
      connectRef.current();
    }
  }, []);

  const clear = useCallback(() => {
    setEvents([]);
    setTotal(0);
  }, []);

  const connect = useCallback(() => {
    if (!enabled || pausedRef.current || !mountedRef.current) return;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = createWorkflowEventSource({
      workflow: filtersRef.current.workflow?.toString(),
      status: filtersRef.current.status?.toString(),
      vehicle_id: filtersRef.current.vehicle_id?.toString(),
      document_id: filtersRef.current.document_id?.toString(),
    });

    eventSourceRef.current = es;
    setStatus("live");
    reconnectAttemptsRef.current = 0;

    es.onopen = () => {
      if (mountedRef.current) {
        setStatus("live");
        reconnectAttemptsRef.current = 0;
      }
    };

    es.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current || pausedRef.current) return;
      try {
        const data = JSON.parse(event.data) as WorkflowEventResponse;
        setEvents((prev) => [data, ...prev].slice(0, 500)); // Keep max 500 events
      } catch {
        // Ignore parse errors
      }
    };

    es.onerror = () => {
      if (!mountedRef.current || pausedRef.current) return;
      setStatus("reconnecting");
      es.close();

      if (reconnectAttemptsRef.current < 10) {
        reconnectAttemptsRef.current += 1;
        setTimeout(() => connectRef.current(), reconnectDelay * reconnectAttemptsRef.current);
      } else {
        setStatus("offline");
      }
    };
  }, [enabled, reconnectDelay]);

  // Initialize connectRef after connect is defined
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const loadMore = useCallback(async () => {
    if (isLoading) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await workflowApi.getRecentEvents({
        ...filtersRef.current,
        offset: filtersRef.current.offset,
      });
      if (!mountedRef.current) return;

      const newEvents = response.items;
      setEvents((prev) => {
        // Merge and deduplicate by event_id
        const existingIds = new Set(prev.map((e) => e.event_id));
        const uniqueNew = newEvents.filter((e) => !existingIds.has(e.event_id));
        return [...uniqueNew, ...prev].slice(0, 500);
      });
      setTotal(response.total);
      setFiltersState((prev) => ({ ...prev, offset: prev.offset + newEvents.length }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, [isLoading]);

  const refetch = useCallback(async () => {
    setFiltersState((prev) => ({ ...prev, offset: 0 }));
    setEvents([]);
    setTotal(0);
    await loadMore();
  }, [loadMore]);

  // Initial load
  useEffect(() => {
    mountedRef.current = true;
    if (enabled) {
      // Defer to avoid synchronous setState in effect
      setTimeout(() => {
        if (mountedRef.current) {
          loadMore();
          connect();
        }
      }, 0);
    }

    return () => {
      mountedRef.current = false;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // Reconnect when filters change (except offset)
  useEffect(() => {
    if (enabled && !pausedRef.current) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setTimeout(() => connectRef.current(), 100);
    }
  }, [filters.workflow, filters.status, filters.vehicle_id, filters.document_id, enabled]);

  return {
    events,
    status,
    total,
    isLoading,
    error,
    loadMore,
    setFilters,
    pause,
    resume,
    clear,
    refetch,
  };
}

export interface UseWorkflowStatusReturn {
  status: WorkflowStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useWorkflowStatus(): UseWorkflowStatusReturn {
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await workflowApi.getWorkflowStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workflow status");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Defer to avoid synchronous setState in effect
    setTimeout(() => {
      refetch();
    }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { status, isLoading, error, refetch };
}
"use client";

import * as React from "react";
import { DEFAULT_RECONNECT_DELAYS } from "@/hooks/use-telemetry-stream";
import { createWorkflowEventSource } from "@/services/workflow";
import type { WorkflowEventResponse } from "@/types/api";

/**
 * Shared workflow stream.
 *
 * Exactly one `EventSource` is opened for the whole authenticated app; every
 * consumer reads from an external store so a consumer scoped to one vehicle
 * does NOT re-render when an unrelated event arrives. Scope filtering happens
 * in the consumer, with a cached slice reference (the "memoized comparator").
 */

export type WorkflowConnection =
  | "connecting"
  | "live"
  | "reconnecting"
  | "disconnected";

export interface WorkflowSliceScope {
  workflow?: string;
  vehicleId?: string;
  documentId?: string;
  correlationId?: string;
  since?: string | number | Date;
}

const MAX_BUFFER = 500;

export interface WorkflowEventSourceLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close: () => void;
}

export type WorkflowEventSourceFactory = () => WorkflowEventSourceLike;

function defaultEventSourceFactory(): WorkflowEventSourceLike {
  return createWorkflowEventSource();
}

interface ResolvedScope {
  workflow?: string;
  vehicleId?: string;
  documentId?: string;
  correlationId?: string;
  sinceMs: number | null;
}

function sliceKey(scope: ResolvedScope): string {
  return [
    scope.workflow ?? "",
    scope.vehicleId ?? "",
    scope.documentId ?? "",
    scope.correlationId ?? "",
    scope.sinceMs ?? "",
  ].join("\u0000");
}

function matches(scope: ResolvedScope, event: WorkflowEventResponse): boolean {
  if (scope.workflow && event.workflow !== scope.workflow) return false;
  if (scope.vehicleId && event.vehicle_id !== scope.vehicleId) return false;
  if (scope.documentId && event.document_id !== scope.documentId) return false;
  if (scope.correlationId && event.correlation_id !== scope.correlationId) {
    return false;
  }
  if (scope.sinceMs !== null && new Date(event.timestamp).getTime() < scope.sinceMs) {
    return false;
  }
  return true;
}

type Listener = () => void;

/**
 * Tiny external store: the provider pushes events, consumers subscribe to the
 * exact slice they care about. `getSlice` keeps a stable array reference while
 * the matching event ids are unchanged, so `useSyncExternalStore` does not
 * re-render a scoped consumer on unrelated events.
 */
class WorkflowStreamStore {
  private events: WorkflowEventResponse[] = [];
  private connection: WorkflowConnection = "connecting";
  private readonly listeners = new Set<Listener>();
  private readonly slices = new Map<
    string,
    { ids: string; result: WorkflowEventResponse[] }
  >();

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getConnection = (): WorkflowConnection => this.connection;

  setConnection(next: WorkflowConnection): void {
    if (this.connection === next) return;
    this.connection = next;
    this.emit();
  }

  push(event: WorkflowEventResponse): void {
    if (this.events.some((existing) => existing.event_id === event.event_id)) {
      return;
    }
    this.events = [event, ...this.events].slice(0, MAX_BUFFER);
    this.emit();
  }

  getSlice = (scope: ResolvedScope): WorkflowEventResponse[] => {
    const key = sliceKey(scope);
    const result = this.events.filter((event) => matches(scope, event));
    const ids = result.map((event) => event.event_id).join("|");
    const cached = this.slices.get(key);
    if (cached && cached.ids === ids) {
      return cached.result;
    }
    this.slices.set(key, { ids, result });
    return result;
  };

  getSnapshot = (): WorkflowEventResponse[] => this.events;

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

const StoreContext = React.createContext<WorkflowStreamStore | null>(null);

interface StreamControls {
  pause: () => void;
  resume: () => void;
}

const ControlsContext = React.createContext<StreamControls | null>(null);

export function WorkflowStreamProvider({
  children,
  eventSourceFactory = defaultEventSourceFactory,
  reconnectDelays = DEFAULT_RECONNECT_DELAYS,
}: {
  children: React.ReactNode;
  eventSourceFactory?: WorkflowEventSourceFactory;
  reconnectDelays?: readonly number[];
}) {
  const [store] = React.useState(() => new WorkflowStreamStore());

  const factoryRef = React.useRef(eventSourceFactory);
  const delaysRef = React.useRef(reconnectDelays);
  React.useEffect(() => {
    factoryRef.current = eventSourceFactory;
    delaysRef.current = reconnectDelays;
  });

  const [paused, setPaused] = React.useState(false);

  React.useEffect(() => {
    if (paused) return;

    let disposed = false;
    let attempt = 0;
    let source: WorkflowEventSourceLike | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const clearTimer = () => {
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const connect = () => {
      if (disposed) return;
      store.setConnection(attempt === 0 ? "connecting" : "reconnecting");

      const next = factoryRef.current();
      source = next;

      next.onopen = () => {
        if (disposed || source !== next) return;
        attempt = 0;
        store.setConnection("live");
      };

      next.onmessage = (message: MessageEvent) => {
        if (disposed || source !== next) return;
        try {
          store.push(JSON.parse(message.data) as WorkflowEventResponse);
        } catch {
          // Ignore heartbeats / malformed frames.
        }
      };

      next.onerror = () => {
        if (disposed || source !== next) return;
        next.close();
        source = null;

        const delays = delaysRef.current;
        if (delays.length === 0) {
          store.setConnection("disconnected");
          return;
        }

        const delay = delays[Math.min(attempt, delays.length - 1)];
        attempt += 1;
        store.setConnection("reconnecting");
        clearTimer();
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      clearTimer();
      if (source) source.close();
      source = null;
    };
  }, [store, paused]);

  const pause = React.useCallback(() => {
    setPaused(true);
    store.setConnection("disconnected");
  }, [store]);

  const resume = React.useCallback(() => {
    setPaused(false);
  }, []);

  const controls = React.useMemo<StreamControls>(() => ({ pause, resume }), [pause, resume]);

  return (
    <StoreContext.Provider value={store}>
      <ControlsContext.Provider value={controls}>
        {children}
      </ControlsContext.Provider>
    </StoreContext.Provider>
  );
}

function useStore(hookName: string): WorkflowStreamStore {
  const store = React.useContext(StoreContext);
  if (!store) {
    throw new Error(`${hookName} must be used within a WorkflowStreamProvider`);
  }
  return store;
}

export function useWorkflowConnection(): WorkflowConnection {
  const store = useStore("useWorkflowConnection");
  return React.useSyncExternalStore(
    store.subscribe,
    store.getConnection,
    store.getConnection,
  );
}

export function useWorkflowSlice(
  scope: WorkflowSliceScope = {},
): { events: WorkflowEventResponse[] } {
  const store = useStore("useWorkflowSlice");
  const resolved = React.useMemo<ResolvedScope>(
    () => ({
      workflow: scope.workflow,
      vehicleId: scope.vehicleId,
      documentId: scope.documentId,
      correlationId: scope.correlationId,
      sinceMs: scope.since != null ? new Date(scope.since).getTime() : null,
    }),
    [
      scope.workflow,
      scope.vehicleId,
      scope.documentId,
      scope.correlationId,
      scope.since,
    ],
  );
  const getSnapshot = React.useCallback(
    () => store.getSlice(resolved),
    [store, resolved],
  );
  return {
    events: React.useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot),
  };
}

export function useWorkflowStreamControls(): StreamControls {
  const controls = React.useContext(ControlsContext);
  if (!controls) {
    throw new Error(
      "useWorkflowStreamControls must be used within a WorkflowStreamProvider",
    );
  }
  return controls;
}

/** Test-only escape hatch: read the raw buffer without scope filtering. */
export function useWorkflowAllEvents(): readonly WorkflowEventResponse[] {
  const store = useStore("useWorkflowAllEvents");
  return React.useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

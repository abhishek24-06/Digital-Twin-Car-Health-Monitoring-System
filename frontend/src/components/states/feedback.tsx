"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw, ShieldAlert, WifiOff, Inbox, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, toApiError } from "@/lib/api-error";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Empty state                                                         */
/* ------------------------------------------------------------------ */

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-line px-6 py-10 text-center",
        className,
      )}
    >
      <div className="flex size-11 items-center justify-center rounded-full bg-surface-3 text-ink-subtle">
        {icon ?? <Inbox className="size-5" aria-hidden />}
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        <div className="mx-auto max-w-md text-xs leading-relaxed text-ink-subtle">
          {description}
        </div>
      </div>
      {action ? <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Error state                                                         */
/* ------------------------------------------------------------------ */

interface Preset {
  title: string;
  message: string;
  icon: React.ReactNode;
}

/** Map a status code onto language a driver actually cares about. */
function presetFor(status: number): Preset | null {
  switch (status) {
    case 0:
      return {
        title: "Cannot reach the Digital Twin API",
        message:
          "The backend did not respond. Check that it is running and that NEXT_PUBLIC_API_URL points at it.",
        icon: <WifiOff className="size-5" aria-hidden />,
      };
    case 401:
      return {
        title: "Your session has expired",
        message: "Sign in again to continue where you left off.",
        icon: <Lock className="size-5" aria-hidden />,
      };
    case 403:
      return {
        title: "You do not have access to this",
        message:
          "This resource belongs to another account, or your role does not permit it.",
        icon: <ShieldAlert className="size-5" aria-hidden />,
      };
    case 404:
      return {
        title: "Not found",
        message: "The item may have been removed, or the link is out of date.",
        icon: <Inbox className="size-5" aria-hidden />,
      };
    case 502:
      return {
        title: "AI provider unavailable",
        message:
          "The reasoning provider could not be reached. Vehicle data is unaffected — retry, or configure a provider key in the backend .env.",
        icon: <AlertTriangle className="size-5" aria-hidden />,
      };
    case 503:
      return {
        title: "Service temporarily unavailable",
        message:
          "A dependency (database, pgvector or RAG models) is unavailable right now.",
        icon: <AlertTriangle className="size-5" aria-hidden />,
      };
    case 504:
      return {
        title: "The request timed out",
        message: "The backend took too long to answer. Try again with a smaller window.",
        icon: <AlertTriangle className="size-5" aria-hidden />,
      };
    default:
      return null;
  }
}

export function ErrorState({
  error,
  className,
  onRetry,
  retryLabel = "Try again",
  compact = false,
}: {
  error: unknown;
  className?: string;
  onRetry?: () => void;
  retryLabel?: string;
  compact?: boolean;
}) {
  const apiError = toApiError(error);
  const preset = presetFor(apiError.status);
  const isApiError = error instanceof ApiError;

  const title =
    preset?.title ??
    (apiError.isValidationError
      ? "Some values are not valid"
      : apiError.isConflict
        ? "Conflicting data"
        : apiError.isServerOrNetwork
          ? "Something went wrong"
          : "Request failed");

  const detail = apiError.message;
  const showBackendDetail = isApiError && detail && detail !== title;

  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-lg border border-[color:color-mix(in_oklab,var(--color-critical)_34%,transparent)]",
        "bg-[color:color-mix(in_oklab,var(--color-critical)_8%,transparent)]",
        compact ? "px-3 py-2.5" : "px-4 py-4",
        className,
      )}
    >
      <div className="mt-0.5 shrink-0 text-[color:var(--color-critical)]">
        {preset?.icon ?? <AlertTriangle className="size-5" aria-hidden />}
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {preset ? (
          <p className="text-xs leading-relaxed text-ink-muted">{preset.message}</p>
        ) : null}
        {showBackendDetail ? (
          <p className="text-xs leading-relaxed text-ink-muted">{detail}</p>
        ) : null}
        {apiError.code ? (
          <p className="font-mono text-[0.68rem] text-ink-subtle">{apiError.code}</p>
        ) : null}
        {onRetry ? (
          <div className="pt-1.5">
            <Button size="sm" variant="outline" onClick={onRetry}>
              <RefreshCw aria-hidden />
              {retryLabel}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Small inline error used above forms / inside panels. */
export function InlineAlert({
  tone = "critical",
  title,
  children,
  className,
}: {
  tone?: "critical" | "attention" | "info";
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "critical"
      ? "text-[color:var(--color-critical)] border-[color:color-mix(in_oklab,var(--color-critical)_34%,transparent)] bg-[color:color-mix(in_oklab,var(--color-critical)_8%,transparent)]"
      : tone === "attention"
        ? "text-[color:var(--color-attention)] border-[color:color-mix(in_oklab,var(--color-attention)_34%,transparent)] bg-[color:color-mix(in_oklab,var(--color-attention)_8%,transparent)]"
        : "text-signal-300 border-[color:color-mix(in_oklab,var(--color-signal-500)_34%,transparent)] bg-[color:color-mix(in_oklab,var(--color-signal-500)_8%,transparent)]";

  return (
    <div
      role="alert"
      className={cn("rounded-lg border px-3 py-2.5", toneClass, className)}
    >
      {title ? <p className="text-xs font-semibold">{title}</p> : null}
      <div className="text-xs leading-relaxed text-ink-muted">{children}</div>
    </div>
  );
}
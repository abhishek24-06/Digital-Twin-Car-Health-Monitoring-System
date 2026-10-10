"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  MinusCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { WorkflowStatus } from "@/types/api";

/**
 * Status vocabulary shared by every contextual pipeline.
 *
 * `WorkflowStatus` is the persisted vocabulary; `"waiting"` is a UI-only
 * state ("no signal yet") that is never emitted or stored.
 */
export type StageStatus = WorkflowStatus | "waiting";

type BadgeTone = NonNullable<BadgeProps["tone"]>;

export interface WorkflowStatusMeta {
  label: string;
  icon: LucideIcon;
  tone: BadgeTone;
  aria: string;
  /** `running`/`connecting` affordances spin their icon. */
  spin?: boolean;
}

export const WORKFLOW_STATUS_META: Record<StageStatus, WorkflowStatusMeta> = {
  started: { label: "Started", icon: Clock, tone: "accent", aria: "Started" },
  running: { label: "Running", icon: Loader2, tone: "accent", aria: "Running", spin: true },
  success: { label: "Success", icon: CheckCircle2, tone: "healthy", aria: "Success" },
  warning: { label: "Warning", icon: AlertTriangle, tone: "attention", aria: "Warning" },
  degraded: { label: "Degraded", icon: AlertTriangle, tone: "attention", aria: "Degraded" },
  skipped: { label: "Skipped", icon: MinusCircle, tone: "unknown", aria: "Skipped" },
  error: { label: "Error", icon: XCircle, tone: "critical", aria: "Error" },
  waiting: { label: "Waiting", icon: Circle, tone: "neutral", aria: "Waiting" },
};

/**
 * A status badge that always renders an icon **and** text, so the meaning is
 * never carried by colour alone. The accessible name mirrors the visible label.
 */
export function WorkflowStatusBadge({ status }: { status: StageStatus }) {
  const meta = WORKFLOW_STATUS_META[status];
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} size="sm" aria-label={meta.aria}>
      <Icon
        className={meta.spin ? "size-3 animate-spin" : "size-3"}
        aria-hidden="true"
      />
      <span>{meta.label}</span>
    </Badge>
  );
}

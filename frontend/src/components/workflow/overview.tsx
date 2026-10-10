"use client";

import * as React from "react";
import {
  Cpu,
  Database,
  FileText,
  Bot,
  GitBranch,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowStatusResponse } from "@/types/api";

interface OverviewProps {
  workflowStatus?: WorkflowStatusResponse | null;
  connectionStatus: "live" | "reconnecting" | "offline";
  totalEvents: number;
  _isLoading: boolean;
}

const PIPELINES = [
  {
    id: "telemetry",
    label: "Telemetry Pipeline",
    description: "Vehicle telemetry from simulator to health snapshot",
    icon: Cpu,
    color: "text-blue-500",
    bg: "bg-blue-50",
    border: "border-blue-200",
    stages: [
      "Simulator",
      "MQTT Publish",
      "Mosquitto",
      "MQTT Subscriber",
      "Parser",
      "PostgreSQL",
      "Health Engine",
      "Health Snapshot",
    ],
    statusKey: "telemetry_pipeline_active" as keyof WorkflowStatusResponse,
  },
  {
    id: "rag",
    label: "RAG Pipeline",
    description: "Document ingestion and query retrieval",
    icon: FileText,
    color: "text-purple-500",
    bg: "bg-purple-50",
    border: "border-purple-200",
    stages: [
      "Document",
      "Parser",
      "Text Extraction",
      "Chunking",
      "Embedding",
      "pgVector",
      "Index",
      "Ready",
    ],
    statusKey: "rag_pipeline_active" as keyof WorkflowStatusResponse,
  },
  {
    id: "agent",
    label: "Agent Pipeline",
    description: "LangGraph agent with vehicle, health, and manufacturer context",
    icon: Bot,
    color: "text-orange-500",
    bg: "bg-orange-50",
    border: "border-orange-200",
    stages: [
      "User Question",
      "Supervisor",
      "Vehicle Context",
      "Health Context",
      "Manufacturer Guidance",
      "Response Generated",
    ],
    statusKey: "agent_pipeline_active" as keyof WorkflowStatusResponse,
  },
];

function PipelineCard({ 
  pipeline, 
  isActive 
}: { 
  pipeline: typeof PIPELINES[0];
  isActive: boolean;
}) {
  return (
    <div className={cn(
      "flex flex-col p-4 rounded-xl border transition-all",
      isActive
        ? pipeline.bg + " " + pipeline.border + " shadow-[0_0_0_1px_theme(colors.signal.400)]"
        : "bg-surface-1 border-line",
    )}>
      <div className="flex items-start gap-3 mb-4">
        <div className={cn(
          "size-10 flex items-center justify-center rounded-lg",
          pipeline.bg + " " + pipeline.color,
        )}>
          <pipeline.icon className="size-5" />
        </div>
        <div className="flex-1">
          <h3 className="font-semibold text-ink">{pipeline.label}</h3>
          <p className="text-sm text-ink-muted mt-1">{pipeline.description}</p>
        </div>
        <div className={cn(
          "flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium",
          isActive
            ? "bg-green-100 text-green-700"
            : "bg-red-100 text-red-700",
        )}>
          {isActive ? (
            <>
              <span className="size-1.5 rounded-full bg-green-500 animate-pulse" />
              Active
            </>
          ) : (
            <>
              <span className="size-1.5 rounded-full bg-red-500" />
              Inactive
            </>
          )}
        </div>
      </div>

      <div className="space-y-2">
        {pipeline.stages.map((stage, index) => (
          <div key={stage} className="flex items-center gap-3 text-sm">
            <span className="size-6 flex items-center justify-center rounded-full bg-surface-2 text-ink-muted font-mono">
              {index + 1}
            </span>
            <span className="text-ink truncate">{stage}</span>
            <span className="ml-auto size-4 text-green-500">✓</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusCard({ 
  label, 
  value, 
  icon, 
  color, 
  bgColor 
}: { 
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}) {
  return (
    <div className={cn("p-4 rounded-xl border", bgColor, "border-line")}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-ink-muted">{label}</span>
        <span className={cn("size-8 flex items-center justify-center rounded-lg", bgColor + " " + color)}>
          {icon}
        </span>
      </div>
      <p className="text-2xl font-bold text-ink">{value}</p>
    </div>
  );
}

function Overview({ 
  workflowStatus, 
  connectionStatus, 
  totalEvents, 
  _isLoading 
}: OverviewProps) {
  const activeSimulations = workflowStatus?.active_simulations ?? 0;
  const subscriberRunning = workflowStatus?.subscriber_running ?? false;

  return (
    <div className="space-y-6">
      {/* System Status Header */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard
          label="Connection"
          value={connectionStatus === "live" ? "Live" : connectionStatus}
          icon={
            connectionStatus === "live" ? (
              <span className="size-5 text-green-500">●</span>
            ) : connectionStatus === "reconnecting" ? (
              <span className="size-5 text-yellow-500 animate-spin">⟳</span>
            ) : (
              <span className="size-5 text-red-500">✗</span>
            )
          }
          color={connectionStatus === "live" ? "text-green-600" : "text-red-600"}
          bgColor="bg-green-50"
        />
        <StatusCard
          label="Events in Buffer"
          value={totalEvents}
          icon={<GitBranch className="size-5" />}
          color="text-blue-600"
          bgColor="bg-blue-50"
        />
        <StatusCard
          label="Active Simulations"
          value={activeSimulations}
          icon={<Cpu className="size-5" />}
          color="text-orange-600"
          bgColor="bg-orange-50"
        />
        <StatusCard
          label="MQTT Subscriber"
          value={subscriberRunning ? "Running" : "Stopped"}
          icon={<Database className="size-5" />}
          color={subscriberRunning ? "text-green-600" : "text-red-600"}
          bgColor={subscriberRunning ? "bg-green-50" : "bg-red-50"}
        />
      </div>

      {/* Pipeline Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {PIPELINES.map((pipeline) => {
          const isActive = Boolean(workflowStatus?.[pipeline.statusKey]) ?? false;
          return <PipelineCard key={pipeline.id} pipeline={pipeline} isActive={isActive} />;
        })}
      </div>

      {/* Architecture Diagram */}
      <div className="p-4 rounded-xl border border-line bg-surface-1">
        <h3 className="font-semibold text-ink mb-4">System Architecture</h3>
        <div className="space-y-3 font-mono text-sm text-ink-muted">
          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded">Simulator</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded">MQTT Publish</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-gray-100 text-gray-700 rounded">Mosquitto</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded">MQTT Subscriber</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-green-100 text-green-700 rounded">Parser</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-green-100 text-green-700 rounded">PostgreSQL</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Health Engine</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Health Snapshot</span>
          </div>
          <div className="flex items-center gap-2 pt-4 border-t border-line">
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Document</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Parser</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Chunking</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Embedding</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">pgVector</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Index</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Retrieve</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Rerank</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded">Answer</span>
          </div>
          <div className="flex items-center gap-2 pt-4 border-t border-t">
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">User</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Supervisor</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Contexts</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Reasoning</span>
            <span className="text-ink-subtle">→</span>
            <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded">Response</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export { Overview };
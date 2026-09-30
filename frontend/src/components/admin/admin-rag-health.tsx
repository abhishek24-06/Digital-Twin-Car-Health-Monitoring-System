"use client";

import * as React from "react";
import { BookOpen, Database, FileText, Layers } from "lucide-react";
import { ErrorState, InlineAlert } from "@/components/states/feedback";
import { useQuery } from "@tanstack/react-query";
import { ragApi } from "@/services/rag";
import { queryKeys } from "@/lib/query-keys";
import type { RagHealthResponse } from "@/types/api";

/**
 * Admin corpus health.
 *
 * `/rag/health` is admin-only on the backend, so a 403 here is a legitimate
 * state to show rather than hide — it proves the server rejected the request.
 */
export function AdminRagHealth() {
  const health = useQuery<RagHealthResponse>({
    queryKey: queryKeys.ragHealth,
    queryFn: ({ signal }) => ragApi.health(signal),
    retry: false,
    staleTime: 30_000,
  });

  if (health.isPending) {
    return <SkeletonRows count={4} />;
  }

  if (health.isError) {
    return <ErrorState error={health.error} onRetry={() => health.refetch()} />;
  }

  const data = health.data;
  const degraded = !data.rag_enabled || !data.pgvector_available;

  return (
    <div className="space-y-3">
      {degraded ? (
        <InlineAlert tone="attention" title="Retrieval is degraded">
          {!data.rag_enabled
            ? "RAG is disabled in the backend environment."
            : "pgvector is not available in the connected database, so semantic search cannot run."}{" "}
          Document ingestion and existing telemetry/health features are unaffected.
        </InlineAlert>
      ) : null}

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact
          icon={BookOpen}
          label="Documents"
          value={String(data.corpus_documents)}
        />
        <Fact
          icon={Layers}
          label="Versions"
          value={String(data.corpus_versions)}
        />
        <Fact
          icon={Database}
          label="Embedded chunks"
          value={String(data.corpus_completed_chunks)}
        />
        <Fact
          icon={FileText}
          label="Embedding dim"
          value={data.embedding_dimension === null ? "—" : String(data.embedding_dimension)}
        />
      </dl>

      <p className="text-[0.68rem] text-ink-subtle">
        embedding model:{" "}
        <span className="font-mono text-ink-muted">
          {data.embedding_model ?? "not configured"}
        </span>
      </p>
    </div>
  );
}

function Fact({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof BookOpen;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-[0.62rem] uppercase tracking-wider text-ink-subtle">
        <Icon className="size-3" aria-hidden />
        {label}
      </dt>
      <dd className="tabular mt-1 text-sm text-ink">{value}</dd>
    </div>
  );
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          className="h-16 animate-pulse rounded-lg border border-line bg-surface-2"
        />
      ))}
    </div>
  );
}

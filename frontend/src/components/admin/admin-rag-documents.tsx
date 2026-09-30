"use client";

import * as React from "react";
import {
  ChevronDown,
  FileText,
  History,
  Search,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/ui/pagination";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, ErrorState } from "@/components/states/feedback";
import { Skeleton } from "@/components/ui/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminRagApi } from "@/services/rag";
import { queryKeys } from "@/lib/query-keys";
import { formatTimestamp } from "@/components/health/health-summary-panel";
import { cn } from "@/lib/utils";
import type { RagDocumentSummary, RagVersionSummary } from "@/types/api";

const PAGE_SIZE = 20;

/** Admin document list with filters, version history and delete. */
export function AdminRagDocuments() {
  const queryClient = useQueryClient();
  const [page, setPage] = React.useState(1);
  const [canonical, setCanonical] = React.useState("");
  const [appliedCanonical, setAppliedCanonical] = React.useState("");
  const [make, setMake] = React.useState("");
  const [model, setModel] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [appliedStatus, setAppliedStatus] = React.useState("");
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<RagDocumentSummary | null>(null);

  const documents = useQuery({
    queryKey: [
      ...queryKeys.ragDocuments,
      page,
      appliedCanonical,
      make,
      model,
      appliedStatus,
    ],
    queryFn: ({ signal }) =>
      adminRagApi.list(
        {
          page,
          pageSize: PAGE_SIZE,
          ...(appliedCanonical ? { canonical: appliedCanonical } : {}),
          ...(make.trim() ? { make: make.trim() } : {}),
          ...(model.trim() ? { model: model.trim() } : {}),
          ...(appliedStatus ? { status: appliedStatus } : {}),
        },
        signal,
      ),
  });

  const remove = useMutation({
    mutationFn: (documentId: string) => adminRagApi.remove(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ragDocuments });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ragHealth });
    },
  });

  const items = documents.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Corpus documents</CardTitle>
          <CardDescription>
            {documents.data
              ? `${documents.data.total} document${documents.data.total === 1 ? "" : "s"}`
              : "Loading corpus…"}
          </CardDescription>
        </div>
      </CardHeader>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setAppliedCanonical(canonical.trim());
          setAppliedStatus(status);
          setPage(1);
        }}
        className="grid gap-3 border-b border-line px-4 py-3 sm:grid-cols-2 lg:grid-cols-5 sm:px-5"
      >
        <div className="lg:col-span-2">
          <label htmlFor="admin-doc-canonical" className="sr-only">
            Filter by canonical name
          </label>
          <Input
            id="admin-doc-canonical"
            value={canonical}
            onChange={(event) => setCanonical(event.target.value)}
            placeholder="canonical name contains…"
            className="h-9"
          />
        </div>
        <div>
          <label htmlFor="admin-doc-make" className="sr-only">
            Filter by make
          </label>
          <Input
            id="admin-doc-make"
            value={make}
            onChange={(event) => setMake(event.target.value)}
            placeholder="make"
            className="h-9"
          />
        </div>
        <div>
          <label htmlFor="admin-doc-model" className="sr-only">
            Filter by model
          </label>
          <Input
            id="admin-doc-model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder="model"
            className="h-9"
          />
        </div>
        <div className="flex gap-2">
          <div>
            <label htmlFor="admin-doc-status" className="sr-only">
              Filter by ingestion status
            </label>
            <select
              id="admin-doc-status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="h-9 w-full rounded-md border border-line bg-surface-2 px-2 text-xs text-ink"
            >
              <option value="">any status</option>
              <option value="ingested">ingested</option>
              <option value="unchanged">unchanged</option>
            </select>
          </div>
          <Button type="submit" size="iconSm" variant="outline" aria-label="Apply filters">
            <Search aria-hidden />
          </Button>
        </div>
      </form>

      <CardContent className="p-0">
        {documents.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : documents.isError ? (
          <ErrorState
            error={documents.error}
            className="m-4"
            onRetry={() => documents.refetch()}
          />
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<FileText className="size-5" aria-hidden />}
              title="No documents match"
              description="Adjust the filters, or ingest a document with the form above."
            />
          </div>
        ) : (
          <ul className="divide-y divide-[color:var(--line)]">
            {items.map((document) => (
              <React.Fragment key={document.id}>
                <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-xs transition-colors hover:bg-surface-2 sm:px-5">
                  <Button
                    size="iconSm"
                    variant="ghost"
                    aria-expanded={expanded === document.id}
                    aria-label={`Toggle version history for ${document.title}`}
                    onClick={() =>
                      setExpanded((current) =>
                        current === document.id ? null : document.id,
                      )
                    }
                  >
                    <ChevronDown
                      className={cn(
                        "transition-transform",
                        expanded === document.id && "rotate-180",
                      )}
                      aria-hidden
                    />
                  </Button>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-ink">{document.title}</p>
                    <p className="mt-0.5 truncate text-[0.65rem] text-ink-subtle">
                      {document.canonical_source ?? "—"} ·{" "}
                      {document.source_type}
                      {document.make ? ` · ${document.make}` : ""}
                      {document.model ? ` ${document.model}` : ""}
                      {document.model_year_start
                        ? ` (${document.model_year_start}${
                            document.model_year_end
                              ? `–${document.model_year_end}`
                              : ""
                          })`
                        : ""}
                    </p>
                  </div>
                  <Badge tone={document.version_count > 1 ? "accent" : "neutral"} size="sm">
                    v{document.version_count}
                  </Badge>
                  <span className="hidden text-[0.65rem] text-ink-subtle sm:inline">
                    {formatTimestamp(document.updated_at)}
                  </span>
                  <Button
                    size="iconSm"
                    variant="ghost"
                    aria-label={`Delete ${document.title}`}
                    className="text-[color:var(--color-critical)] hover:bg-surface-2"
                    onClick={() => setPendingDelete(document)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </li>
                {expanded === document.id ? (
                  <li className="bg-surface-2 px-4 py-3 sm:px-5">
                    <VersionHistory documentId={document.id} />
                  </li>
                ) : null}
              </React.Fragment>
            ))}
          </ul>
        )}

        {documents.data && documents.data.total > 0 ? (
          <Pagination
            page={documents.data.page}
            pageSize={documents.data.page_size}
            total={documents.data.total}
            onPageChange={setPage}
            label="Corpus documents"
          />
        ) : null}
      </CardContent>

      <Dialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this document?</DialogTitle>
            <DialogDescription>
              {pendingDelete
                ? `“${pendingDelete.title}” and all ${pendingDelete.version_count} version(s), their chunks and embeddings will be removed in a single transaction. This cannot be undone.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {remove.isError ? <ErrorState error={remove.error} compact /> : null}
          </DialogBody>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setPendingDelete(null)}
              disabled={remove.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={async () => {
                if (!pendingDelete) return;
                await remove.mutateAsync(pendingDelete.id).catch(() => undefined);
                setPendingDelete(null);
              }}
            >
              <Trash2 aria-hidden />
              Delete document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function VersionHistory({ documentId }: { documentId: string }) {
  const detail = useQuery({
    queryKey: queryKeys.ragDocument(documentId),
    queryFn: ({ signal }) => adminRagApi.get(documentId, signal),
  });

  if (detail.isPending) {
    return <Skeleton className="h-24 w-full" />;
  }
  if (detail.isError) {
    return <ErrorState error={detail.error} compact onRetry={() => detail.refetch()} />;
  }

  const versions: RagVersionSummary[] = detail.data?.versions ?? [];

  if (versions.length === 0) {
    return <p className="text-xs text-ink-subtle">No versions recorded.</p>;
  }

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 text-[0.65rem] uppercase tracking-wider text-ink-subtle">
        <History className="size-3" aria-hidden />
        version history
      </p>
      <ul className="space-y-1.5">
        {versions.map((version) => (
          <li
            key={version.id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line bg-surface px-3 py-2 text-[0.68rem]"
          >
            <span className="tabular font-medium text-ink">v{version.version}</span>
            <span className="text-ink-muted">{version.source_filename}</span>
            <span className="text-ink-subtle">
              {version.parser_name}
              {version.parser_version ? ` v${version.parser_version}` : ""}
            </span>
            <span className="text-ink-subtle">{version.chunk_count} chunks</span>
            {version.page_count !== null ? (
              <span className="text-ink-subtle">{version.page_count} pages</span>
            ) : null}
            <Badge
              size="sm"
              tone={
                version.ingestion_status === "completed"
                  ? "healthy"
                  : version.ingestion_status === "failed"
                    ? "critical"
                    : "attention"
              }
            >
              {version.ingestion_status}
            </Badge>
            <span className="tabular ml-auto text-ink-subtle">
              {formatTimestamp(version.created_at)}
            </span>
            {version.error_message ? (
              <span className="w-full text-[color:var(--color-critical)]">
                {version.error_message}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

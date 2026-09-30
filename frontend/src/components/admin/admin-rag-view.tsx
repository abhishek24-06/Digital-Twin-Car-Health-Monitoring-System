"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { InlineAlert } from "@/components/states/feedback";
import { PageHeader } from "@/components/layout/page-header";
import { AdminRagHealth } from "@/components/admin/admin-rag-health";
import { AdminRagDocuments } from "@/components/admin/admin-rag-documents";
import { AdminRagUploadDialog, type UploadOutcome } from "@/components/admin/admin-rag-upload";
import { AuthenticatedShell } from "@/components/layout/app-shell";
import { useSessionStore } from "@/lib/session-store";

/**
 * Admin RAG console.
 *
 * The route is guarded client-side for usability, but every endpoint is
 * authorised server-side; a non-admin who lands here sees the API's own 403.
 */
export function AdminRagView() {
  const router = useRouter();
  const isAdmin = useSessionStore((state) => state.user?.role === "admin");
  const [lastUpload, setLastUpload] = React.useState<UploadOutcome | null>(null);

  if (!isAdmin) {
    return (
      <div className="space-y-4">
        <PageHeader title="Admin · RAG corpus" />
        <InlineAlert tone="critical" title="Administrator access required">
          This account does not have the administrator role, so corpus health,
          ingestion and deletion are unavailable. The backend rejects these requests
          with 403.
        </InlineAlert>
        <Card>
          <CardContent className="flex items-center gap-3">
            <ShieldAlert className="size-5 text-[color:var(--color-critical)]" aria-hidden />
            <div>
              <p className="text-sm text-ink">Nothing to see here</p>
              <p className="text-xs text-ink-subtle">
                Ask an administrator to grant access if you believe this is a mistake.
              </p>
            </div>
          </CardContent>
        </Card>
        <button
          type="button"
          onClick={() => router.replace("/dashboard")}
          className="rounded text-xs text-signal-400 underline-offset-4 hover:underline"
        >
          Back to dashboard
        </button>
      </div>
    );
  }

  return (
    <AuthenticatedShell requireAdmin>
      <div className="space-y-5">
        <PageHeader
          title="Admin · RAG corpus"
          description="Corpus health, document ingestion and version management for the retrieval layer used by AI diagnoses."
        />

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Corpus health</CardTitle>
              <CardDescription>
                Live status from <code className="font-mono">GET /rag/health</code>
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <AdminRagHealth />
          </CardContent>
        </Card>

        <AdminRagUploadDialog onUploaded={setLastUpload} />

        {lastUpload ? (
          <InlineAlert
            tone={lastUpload.response.status === "unchanged" ? "info" : "info"}
            title={
              lastUpload.response.status === "unchanged"
                ? "Content already ingested"
                : "Document ingested"
            }
          >
            <span className="font-mono">{lastUpload.fileName}</span> →{" "}
            <span className="font-mono">{lastUpload.response.canonical}</span>
            {lastUpload.response.status === "unchanged"
              ? " matched an existing content hash, so no new version was created."
              : ` created version ${lastUpload.response.version} with ${lastUpload.response.chunks_created} chunks using ${lastUpload.response.embedding_model ?? "the configured model"}.`}
          </InlineAlert>
        ) : null}

        <AdminRagDocuments />
      </div>
    </AuthenticatedShell>
  );
}

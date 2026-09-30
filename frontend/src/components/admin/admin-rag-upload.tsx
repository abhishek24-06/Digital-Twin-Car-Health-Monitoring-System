"use client";

import * as React from "react";
import { UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { ErrorState, InlineAlert } from "@/components/states/feedback";
import { adminRagApi } from "@/services/rag";
import { toApiError } from "@/lib/api-error";
import type { AdminRagUploadForm, AdminRagUploadResponse } from "@/types/api";

/**
 * Accepted formats, mirroring the backend parser registry exactly:
 * `DOCLING_EXTENSIONS` (`.pdf .docx .doc .rtf .pptx .ppt .html .mhtml .xlsx
 * .xls .odt .ods .odp .epub`) plus `PLAIN_TEXT_EXTENSIONS`
 * (`.txt .md .text`) in `app/rag/parser/docling.py`. Anything outside this set
 * is rejected server-side, so it must not be advertised in the file picker.
 */
const ACCEPT =
  ".pdf,.docx,.doc,.rtf,.pptx,.ppt,.html,.mhtml,.xlsx,.xls,.odt,.ods,.odp,.epub,.txt,.md,.text";

export interface UploadOutcome {
  response: AdminRagUploadResponse;
  fileName: string;
}

/**
 * Multipart ingestion form.
 *
 * The file goes to the real endpoint with `multipart/form-data`; there is no
 * client-side "fake" ingestion path.
 */
export function AdminRagUploadDialog({
  onUploaded,
}: {
  onUploaded: (outcome: UploadOutcome) => void;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [canonical, setCanonical] = React.useState("");
  const [make, setMake] = React.useState("");
  const [model, setModel] = React.useState("");
  const [year, setYear] = React.useState("");
  const [yearEnd, setYearEnd] = React.useState("");
  const [manufacturer, setManufacturer] = React.useState("");
  const [documentType, setDocumentType] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [uploading, setUploading] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [dragActive, setDragActive] = React.useState(false);

  const inputRef = React.useRef<HTMLInputElement>(null);

  const pickFile = (next: File | null) => {
    setFile(next);
    // Suggest a canonical name from the filename; the admin can override it.
    if (next) {
      const base = next.name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9]+/g, "_");
      setCanonical((current) => current || base.toLowerCase().slice(0, 120));
    }
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const meta: AdminRagUploadForm = {
        canonical: canonical.trim(),
        ...(make.trim() ? { make: make.trim() } : {}),
        ...(model.trim() ? { model: model.trim() } : {}),
        ...(year.trim() ? { year: Number(year) } : {}),
        ...(yearEnd.trim() ? { year_end: Number(yearEnd) } : {}),
        ...(manufacturer.trim() ? { manufacturer: manufacturer.trim() } : {}),
        ...(documentType.trim() ? { document_type: documentType.trim() } : {}),
        ...(language.trim() ? { language: language.trim() } : {}),
      };
      const response = await adminRagApi.upload(file, meta);
      onUploaded({ response, fileName: file.name });
      setFile(null);
      setCanonical("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Ingest a document</CardTitle>
          <CardDescription>
            Parsed, chunked and embedded by the backend. Re-uploading identical content
            is detected by hash and does not create a duplicate version.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} noValidate className="space-y-4">
          {error ? <ErrorState error={error} compact /> : null}

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              pickFile(event.dataTransfer.files?.[0] ?? null);
            }}
            className={`rounded-lg border border-dashed px-4 py-6 text-center transition-colors ${
              dragActive ? "border-signal-500 bg-signal-500/5" : "border-line"
            }`}
          >
            <label htmlFor="rag-file" className="sr-only">
              Document to ingest
            </label>
            <input
              ref={inputRef}
              id="rag-file"
              type="file"
              accept={ACCEPT}
              className="sr-only"
              onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            />
            <UploadCloud className="mx-auto size-6 text-ink-subtle" aria-hidden />
            <p className="mt-2 text-sm text-ink">
              {file ? file.name : "Drop a file here or choose one"}
            </p>
            <p className="mt-1 text-[0.68rem] text-ink-subtle">
              PDF, Word, PowerPoint, Excel, EPUB, HTML, plain text and markdown. The size
              limit is enforced by the backend (RAG_MAX_UPLOAD_SIZE_MB).
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => inputRef.current?.click()}
            >
              Choose file
            </Button>
          </div>

          <Field
            label="Canonical name"
            htmlFor="rag-canonical"
            required
            hint="Stable identity for re-ingestion, e.g. civic_2019_service_manual."
          >
            <Input
              id="rag-canonical"
              value={canonical}
              maxLength={120}
              onChange={(event) => setCanonical(event.target.value)}
              placeholder="civic_2019_service_manual"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Manufacturer" htmlFor="rag-manufacturer" hint="Optional">
              <Input
                id="rag-manufacturer"
                value={manufacturer}
                maxLength={120}
                onChange={(event) => setManufacturer(event.target.value)}
                placeholder="Honda"
              />
            </Field>
            <Field label="Document type" htmlFor="rag-document-type" hint="Optional">
              <Input
                id="rag-document-type"
                value={documentType}
                maxLength={80}
                onChange={(event) => setDocumentType(event.target.value)}
                placeholder="service_manual"
              />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-4">
            <Field label="Make" htmlFor="rag-make" hint="Optional">
              <Input
                id="rag-make"
                value={make}
                maxLength={64}
                onChange={(event) => setMake(event.target.value)}
                placeholder="Honda"
              />
            </Field>
            <Field label="Model" htmlFor="rag-model" hint="Optional">
              <Input
                id="rag-model"
                value={model}
                maxLength={128}
                onChange={(event) => setModel(event.target.value)}
                placeholder="Civic"
              />
            </Field>
            <Field label="Year from" htmlFor="rag-year" hint="1900–2100">
              <Input
                id="rag-year"
                type="number"
                min={1900}
                max={2100}
                value={year}
                onChange={(event) => setYear(event.target.value)}
              />
            </Field>
            <Field label="Year to" htmlFor="rag-year-end" hint="Optional range end">
              <Input
                id="rag-year-end"
                type="number"
                min={1900}
                max={2100}
                value={yearEnd}
                onChange={(event) => setYearEnd(event.target.value)}
              />
            </Field>
          </div>

          <Field label="Language" htmlFor="rag-language" hint="Optional, e.g. en">
            <Input
              id="rag-language"
              value={language}
              maxLength={16}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="en"
            />
          </Field>

          <InlineAlert tone="info">
            Version history is preserved. Deleting a document removes every version,
            chunk and embedding for it in one transaction.
          </InlineAlert>

          <Button type="submit" loading={uploading} disabled={!file || !canonical.trim()}>
            <UploadCloud aria-hidden />
            Ingest document
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

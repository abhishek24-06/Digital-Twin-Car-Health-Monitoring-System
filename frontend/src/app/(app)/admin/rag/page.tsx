import type { Metadata } from "next";
import { AdminRagView } from "@/components/admin/admin-rag-view";

export const metadata: Metadata = {
  title: "Admin · RAG corpus",
  description: "Corpus health, ingestion and document management.",
};

export default function AdminRagPage() {
  return <AdminRagView />;
}

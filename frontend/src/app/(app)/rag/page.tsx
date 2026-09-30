import type { Metadata } from "next";
import { RagSearchView } from "@/components/rag/rag-search-view";

export const metadata: Metadata = {
  title: "Manufacturer guidance",
  description: "Search the ingested documentation corpus for passages relevant to your vehicle.",
};

export default function RagPage() {
  return <RagSearchView />;
}

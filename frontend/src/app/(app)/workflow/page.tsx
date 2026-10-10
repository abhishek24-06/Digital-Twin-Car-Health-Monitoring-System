import type { Metadata } from "next";
import { WorkflowView } from "@/components/workflow/workflow-view";

export const metadata: Metadata = {
  title: "Workflow Monitor",
  description: "Real-time observability of the Digital Twin execution pipeline",
};

export default function WorkflowPage() {
  return <WorkflowView />;
}
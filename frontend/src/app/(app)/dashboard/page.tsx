import type { Metadata } from "next";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = {
  title: "Vehicle Intelligence Overview",
  description:
    "Fleet-level view of telemetry freshness, health assessments and attention across every vehicle you can access.",
};

export default function DashboardPage() {
  return <DashboardView />;
}

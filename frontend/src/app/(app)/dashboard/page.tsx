import type { Metadata } from "next";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Health score, telemetry and diagnoses for your active vehicle.",
};

export default function DashboardPage() {
  return <DashboardView />;
}

import type { Metadata } from "next";
import { SimulationsView } from "@/components/simulations/simulations-view";

export const metadata: Metadata = {
  title: "Simulation Control",
  description: "Start and stop the telemetry simulator for each vehicle.",
};

export default function SimulationsPage() {
  return <SimulationsView />;
}
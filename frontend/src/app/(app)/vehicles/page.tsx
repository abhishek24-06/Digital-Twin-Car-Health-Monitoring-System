import type { Metadata } from "next";
import { VehiclesView } from "@/components/vehicles/vehicles-view";

export const metadata: Metadata = {
  title: "My vehicles",
  description: "Register and manage the vehicles you monitor.",
};

export default function VehiclesPage() {
  return <VehiclesView />;
}

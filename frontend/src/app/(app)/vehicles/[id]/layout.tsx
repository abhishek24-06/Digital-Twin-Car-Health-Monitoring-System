import type { Metadata } from "next";
import type { ReactNode } from "react";
import { VehicleWorkspace } from "@/components/vehicles/vehicle-workspace";

export const metadata: Metadata = {
  title: "Vehicle",
};

/**
 * Shared chrome for every `/vehicles/[id]/*` route so switching tabs keeps the
 * vehicle header and tab bar mounted.
 */
export default function VehicleLayout({ children }: { children: ReactNode }) {
  return <VehicleWorkspace>{children}</VehicleWorkspace>;
}

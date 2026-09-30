"use client";

import { create } from "zustand";

/**
 * The vehicle the user is currently working on, shared by the sidebar, top bar
 * and dashboard. Persisted so a reload keeps the same context. This is a
 * presentation preference only — the backend re-validates access to the id.
 */
interface VehicleSelectionState {
  selectedVehicleId: string | null;
  select: (vehicleId: string | null) => void;
}

const STORAGE_KEY = "dt-selected-vehicle";

function readStored(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export const useVehicleSelection = create<VehicleSelectionState>((set) => ({
  selectedVehicleId: readStored(),
  select: (vehicleId) => {
    set({ selectedVehicleId: vehicleId });
    if (typeof window === "undefined") return;
    if (vehicleId) window.localStorage.setItem(STORAGE_KEY, vehicleId);
    else window.localStorage.removeItem(STORAGE_KEY);
  },
}));
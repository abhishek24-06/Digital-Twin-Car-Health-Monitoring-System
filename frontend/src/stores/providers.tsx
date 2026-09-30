"use client";

import * as React from "react";
import { ThemeProvider } from "@/stores/theme-provider";
import { QueryProvider } from "@/stores/query-provider";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * Client-side providers. Order matters: theme first (so tooltips/portals paint
 * correctly), then the query cache, then tooltip context.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
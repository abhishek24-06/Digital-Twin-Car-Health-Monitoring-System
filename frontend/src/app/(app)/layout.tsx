import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/layout/app-shell";

/**
 * Layout for every authenticated route: sidebar, top bar and the skip-link
 * target. Protection itself is handled by `useAuthGuard` inside the shell,
 * because the session lives in an httpOnly cookie + in-memory token.
 *
 * The shell reads search params for active-navigation highlighting, so it is
 * wrapped in Suspense to keep these routes statically prerenderable.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={null}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}

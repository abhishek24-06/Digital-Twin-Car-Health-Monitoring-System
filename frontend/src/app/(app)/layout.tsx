import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { WorkflowStreamProvider } from "@/components/workflow/workflow-stream-provider";

/**
 * Layout for every authenticated route: sidebar, top bar and the skip-link
 * target. Protection itself is handled by `useAuthGuard` inside the shell,
 * because the session lives in an httpOnly cookie + in-memory token.
 *
 * The shared workflow stream is mounted **here**, at the `(app)` layout
 * boundary, so every workflow consumer in the authenticated area (e.g. the
 * diagnosis page's `ContextualPipeline`) is always inside the provider —
 * regardless of auth-state transitions (`loading` → `authenticated`/`anonymous`).
 * Exactly one `EventSource` is opened for the whole authenticated area, and it
 * survives shell re-renders caused by the auth guard.
 *
 * The shell reads search params for active-navigation highlighting, so it is
 * wrapped in Suspense to keep these routes statically prerenderable.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <WorkflowStreamProvider>
      <Suspense fallback={null}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </WorkflowStreamProvider>
  );
}

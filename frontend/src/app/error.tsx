"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/states/feedback";

/**
 * Route-level error boundary.
 *
 * Only genuinely unexpected render failures land here; expected API failures are
 * handled in the components themselves with domain-specific empty/error states.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Surfaced for debugging; the UI itself stays generic.
    console.error("Unhandled route error", error);
  }, [error]);

  return (
    <main className="flex min-h-dvh items-center justify-center px-6">
      <div className="w-full max-w-md space-y-4">
        <ErrorState error={error} onRetry={reset} />
        <div className="flex justify-center">
          <Button size="sm" variant="outline" onClick={reset}>
            Try again
          </Button>
        </div>
        {error.digest ? (
          <p className="text-center font-mono text-[0.65rem] text-ink-subtle">
            reference: {error.digest}
          </p>
        ) : null}
      </div>
    </main>
  );
}

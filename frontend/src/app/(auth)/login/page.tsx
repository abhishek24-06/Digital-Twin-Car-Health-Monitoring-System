import { Suspense } from "react";
import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in",
};

/**
 * Client-side routes cannot read `searchParams` during prerender, so the form is
 * wrapped in Suspense as Next requires.
 */
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center">
          <p className="text-xs text-ink-subtle">Loading sign in…</p>
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}

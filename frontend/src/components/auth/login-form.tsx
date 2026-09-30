"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { LogIn } from "lucide-react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorState, InlineAlert } from "@/components/states/feedback";
import { authApi } from "@/services/auth";
import { toApiError } from "@/lib/api-error";
import { useSessionStore } from "@/lib/session-store";
import { useSessionBootstrap } from "@/hooks/use-auth-guard";

/** Only same-site relative paths are honoured for post-login redirects. */
function safeNext(raw: string | null): string {
  if (!raw) return "/dashboard";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/dashboard";
  return raw;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useSessionStore((state) => state.setSession);
  useSessionBootstrap();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string[]>>({});

  const next = safeNext(searchParams.get("next"));
  const denied = searchParams.get("denied");
  const notice =
    denied === "admin" ? "That area requires an administrator account." : null;

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError(null);
    setFieldErrors({});
    try {
      const payload = await authApi.login({ email: email.trim(), password });
      if (!payload.access_token || !payload.user) {
        throw new Error("The server did not return a session.");
      }
      setSession({
        access_token: payload.access_token,
        expires_at: payload.expires_at ?? null,
        user: payload.user,
      });
      router.replace(next);
      router.refresh();
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      setFieldErrors(apiError.fieldErrors);
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Access your vehicles, telemetry and health history."
      footer={
        <>
          New here?{" "}
          <Link
            href="/register"
            className="rounded font-medium text-signal-400 underline-offset-4 hover:underline"
          >
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {notice ? <InlineAlert tone="info">{notice}</InlineAlert> : null}
        {error ? <ErrorState error={error} compact /> : null}

        <Field
          label="Email"
          htmlFor="email"
          required
          error={fieldErrors.email?.[0]}
        >
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            value={email}
            invalid={Boolean(fieldErrors.email)}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="driver@example.com"
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          required
          error={fieldErrors.password?.[0]}
        >
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            invalid={Boolean(fieldErrors.password)}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        <Button type="submit" block size="lg" loading={submitting}>
          <LogIn aria-hidden />
          Sign in
        </Button>

        <p className="text-[0.68rem] leading-relaxed text-ink-subtle">
          Sessions use a short-lived access token held in memory and a rotating
          refresh token stored in an httpOnly cookie, so closing the tab ends the
          session without leaving credentials in the browser.
        </p>
      </form>
    </AuthLayout>
  );
}

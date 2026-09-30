"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserPlus } from "lucide-react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorState, InlineAlert } from "@/components/states/feedback";
import { authApi } from "@/services/auth";
import { toApiError } from "@/lib/api-error";
import { useSessionStore } from "@/lib/session-store";

const PASSWORD_MIN = 8;
const PASSWORD_MAX = 72;

/**
 * Registration mirrors the backend contract exactly: `POST /auth/register`
 * returns only the created user (201), so this form calls the session proxy,
 * which then signs the new account in automatically.
 */
export function RegisterForm() {
  const router = useRouter();
  const setSession = useSessionStore((state) => state.setSession);

  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string[]>>({});
  const [localErrors, setLocalErrors] = React.useState<Record<string, string>>({});

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!email.trim()) errors.email = "Enter your email address.";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      errors.email = "Enter a valid email address.";

    if (!password) errors.password = "Choose a password.";
    else if (password.length < PASSWORD_MIN)
      errors.password = `Use at least ${PASSWORD_MIN} characters.`;
    else if (password.length > PASSWORD_MAX)
      errors.password = `Use at most ${PASSWORD_MAX} characters.`;

    if (confirm !== password) errors.confirm = "Passwords do not match.";

    setLocalErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setFieldErrors({});
    if (!validate()) return;

    setSubmitting(true);
    try {
      const payload = await authApi.register({
        email: email.trim(),
        password,
        full_name: fullName.trim() ? fullName.trim() : null,
      });
      if (!payload.access_token || !payload.user) {
        throw new Error("The account was created but sign-in did not complete.");
      }
      setSession({
        access_token: payload.access_token,
        expires_at: payload.expires_at ?? null,
        user: payload.user,
      });
      router.replace("/vehicles?welcome=1");
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      setFieldErrors(apiError.fieldErrors);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="One account per driver. You will be signed in automatically."
      footer={
        <>
          Already registered?{" "}
          <Link
            href="/login"
            className="rounded font-medium text-signal-400 underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {error ? <ErrorState error={error} compact /> : null}

        <Field
          label="Full name"
          htmlFor="full_name"
          hint="Optional. Shown on your vehicles and diagnoses."
          error={localErrors.full_name ?? fieldErrors.full_name?.[0]}
        >
          <Input
            id="full_name"
            name="full_name"
            autoComplete="name"
            maxLength={120}
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </Field>

        <Field
          label="Email"
          htmlFor="email"
          required
          error={localErrors.email ?? fieldErrors.email?.[0]}
        >
          <Input
            id="email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            invalid={Boolean(localErrors.email || fieldErrors.email)}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="driver@example.com"
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          required
          hint={`${PASSWORD_MIN}–${PASSWORD_MAX} characters.`}
          error={localErrors.password ?? fieldErrors.password?.[0]}
        >
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN}
            maxLength={PASSWORD_MAX}
            value={password}
            invalid={Boolean(localErrors.password || fieldErrors.password)}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        <Field
          label="Confirm password"
          htmlFor="confirm"
          required
          error={localErrors.confirm}
        >
          <Input
            id="confirm"
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            invalid={Boolean(localErrors.confirm)}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </Field>

        <Button type="submit" block size="lg" loading={submitting}>
          <UserPlus aria-hidden />
          Create account
        </Button>

        <InlineAlert tone="info">
          Accounts are created with the standard driver role. Access to vehicle data
          is scoped to your account by the backend on every request.
        </InlineAlert>
      </form>
    </AuthLayout>
  );
}

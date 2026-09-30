"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut, Save, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/input";
import { ErrorState, InlineAlert } from "@/components/states/feedback";
import { PageHeader } from "@/components/layout/page-header";
import { authApi } from "@/services/auth";
import { toApiError } from "@/lib/api-error";
import { useSessionStore } from "@/lib/session-store";
import { clearQueryCache } from "@/stores/query-provider";
import type { UserResponse } from "@/types/api";

/** Profile: identity, role (read-only) and display-name editing. */
export function ProfileView() {
  const router = useRouter();
  const user = useSessionStore((state) => state.user);
  const setAnonymous = useSessionStore((state) => state.setAnonymous);
  const [signingOut, setSigningOut] = React.useState(false);

  if (!user) {
    return (
      <div className="space-y-5">
        <PageHeader title="Profile" />
        <p className="text-xs text-ink-subtle">Loading your account…</p>
      </div>
    );
  }

  const signOut = async () => {
    setSigningOut(true);
    try {
      await authApi.logout();
    } finally {
      // Drop the in-memory access token even if the cookie call failed, and
      // evict every owner-scoped response so no authenticated data stays
      // readable from this tab by whoever logs in next.
      setAnonymous();
      clearQueryCache();
      setSigningOut(false);
      router.replace("/login");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Profile"
        description="Your account details. Role and email are managed by the backend and cannot be changed here."
        actions={
          <Button
            variant="outline"
            size="sm"
            loading={signingOut}
            onClick={signOut}
          >
            <LogOut aria-hidden />
            Sign out
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Remounting on the authoritative value keeps the input in sync when
            the session is refreshed elsewhere without discarding typing. */}
        <ProfileForm key={user.full_name ?? ""} user={user} />

        <Card>
          <CardHeader>
            <CardTitle>Access</CardTitle>
            <CardDescription>Assigned by the backend</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-ink-subtle">Role</span>
              <Badge tone={user.role === "admin" ? "accent" : "neutral"}>
                {user.role}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-ink-subtle">Status</span>
              <Badge tone={user.is_active ? "healthy" : "critical"}>
                {user.is_active ? "active" : "disabled"}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-ink-subtle">Member since</span>
              <span className="tabular text-ink">
                {new Date(user.created_at).toLocaleDateString()}
              </span>
            </div>

            {user.role === "admin" ? (
              <p className="flex gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[0.68rem] leading-relaxed text-ink-subtle">
                <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-signal-400" aria-hidden />
                Administrators can reach the RAG corpus console. Every admin action is
                still authorised server-side on each request.
              </p>
            ) : (
              <p className="rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[0.68rem] leading-relaxed text-ink-subtle">
                You can only see and manage vehicles owned by your account. The API
                rejects requests for any other vehicle with 403.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ProfileForm({ user }: { user: UserResponse }) {
  const setUser = useSessionStore((state) => state.setUser);
  const [fullName, setFullName] = React.useState(user.full_name ?? "");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [saved, setSaved] = React.useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const trimmed = fullName.trim();
      const updated = await authApi.updateProfile(trimmed ? trimmed : null);
      setUser(updated);
      setSaved(true);
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <div>
          <CardTitle>Account details</CardTitle>
          <CardDescription>Changes apply immediately across the app</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {error ? <ErrorState error={error} compact /> : null}
          {saved ? <InlineAlert tone="info">Profile updated.</InlineAlert> : null}

          <Field
            label="Display name"
            htmlFor="profile-full-name"
            hint="Used on vehicles and in shared diagnoses. Up to 120 characters."
          >
            <Input
              id="profile-full-name"
              value={fullName}
              maxLength={120}
              autoComplete="name"
              placeholder="Your name"
              onChange={(event) => setFullName(event.target.value)}
            />
          </Field>

          <Field
            label="Email"
            htmlFor="profile-email"
            hint="Contact support to change the email on an account."
          >
            <Input id="profile-email" value={user.email} readOnly disabled />
          </Field>

          <Button type="submit" loading={saving}>
            <Save aria-hidden />
            Save changes
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

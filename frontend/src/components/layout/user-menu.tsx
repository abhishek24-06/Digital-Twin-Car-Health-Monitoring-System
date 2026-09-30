"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  LogOut,
  Moon,
  Settings,
  Sun,
  User as UserIcon,
  CircleUser,
} from "lucide-react";
import { useTheme } from "@/stores/theme-provider";
import { useSessionStore } from "@/lib/session-store";
import { authApi } from "@/services/auth";
import { Button } from "@/components/ui/button";

/** Profile + theme + sign-out menu for the top bar. */
export function UserMenu() {
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const user = useSessionStore((state) => state.user);
  const setAnonymous = useSessionStore((state) => state.setAnonymous);
  const [signingOut, setSigningOut] = React.useState(false);

  if (!user) return null;

  const initials =
    (user.full_name?.trim().slice(0, 2) || user.email.slice(0, 2)).toUpperCase();

  const handleSignOut = async () => {
    setSigningOut(true);
    try {
      // Revoke the refresh token server-side, then clear local state.
      await authApi.logout();
    } finally {
      setAnonymous();
      setSigningOut(false);
      router.replace("/login");
    }
  };

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-md border border-line bg-surface-2 py-1 pl-1 pr-2 transition-colors hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400"
          aria-label="Account menu"
        >
          <span
            className="grid size-7 place-items-center rounded-md bg-signal-500/15 text-[0.7rem] font-semibold text-signal-300"
            aria-hidden
          >
            {initials}
          </span>
          <span className="hidden max-w-32 truncate text-xs text-ink-muted sm:inline">
            {user.full_name || user.email}
          </span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 rounded-lg border border-line bg-surface p-1 shadow-[var(--shadow-pop)]"
        >
          <div className="px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
              <CircleUser className="size-3.5 text-ink-subtle" aria-hidden />
              {user.full_name || "Signed in"}
            </p>
            <p className="mt-0.5 truncate text-xs text-ink-subtle">{user.email}</p>
            <p className="mt-1.5 inline-flex rounded border border-line px-1.5 py-0.5 text-[0.62rem] uppercase tracking-wider text-ink-subtle">
              {user.role}
            </p>
          </div>

          <DropdownMenu.Separator className="my-1 h-px bg-[color:var(--line)]" />

          <DropdownMenu.Item asChild>
            <Link
              href="/profile"
              className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm text-ink outline-none data-[highlighted]:bg-surface-2"
            >
              <Settings className="size-3.5 text-ink-subtle" aria-hidden />
              Profile settings
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <button
              type="button"
              onClick={toggleTheme}
              className="flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm text-ink outline-none data-[highlighted]:bg-surface-2"
            >
              {theme === "dark" ? (
                <Sun className="size-3.5 text-ink-subtle" aria-hidden />
              ) : (
                <Moon className="size-3.5 text-ink-subtle" aria-hidden />
              )}
              Switch to {theme === "dark" ? "light" : "dark"} theme
            </button>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1 h-px bg-[color:var(--line)]" />

          <DropdownMenu.Item asChild>
            <Button
              variant="ghost"
              size="sm"
              block
              loading={signingOut}
              onClick={handleSignOut}
              className="justify-start text-[color:var(--color-critical)] hover:bg-surface-2"
            >
              <LogOut aria-hidden />
              Sign out
            </Button>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** Compact theme toggle for the mobile bar. */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
    </Button>
  );
}

/** Re-exported for the profile page header. */
export { UserIcon };

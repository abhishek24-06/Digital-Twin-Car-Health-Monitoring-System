"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronRight,
  Home,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface Crumb {
  label: string;
  href?: string;
  icon?: LucideIcon;
}

/**
 * Route-level breadcrumb + page heading. The vehicle id in the path is resolved
 * to a human label by the caller (which already has the vehicle loaded), so the
 * trail never shows a raw UUID.
 */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  breadcrumbs?: Crumb[];
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <nav aria-label="Breadcrumb">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-ink-subtle">
            <li>
              <a
                href="/dashboard"
                className="inline-flex items-center gap-1 rounded transition-colors hover:text-ink"
              >
                <Home className="size-3" aria-hidden />
                Dashboard
              </a>
            </li>
            {breadcrumbs.map((crumb, index) => {
              const isLast = index === breadcrumbs.length - 1;
              return (
                <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                  <ChevronRight className="size-3 text-ink-subtle" aria-hidden />
                  {crumb.href && !isLast ? (
                    <a
                      href={crumb.href}
                      className="rounded transition-colors hover:text-ink"
                    >
                      {crumb.label}
                    </a>
                  ) : (
                    <span aria-current={isLast ? "page" : undefined} className="text-ink-muted">
                      {crumb.label}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight text-ink sm:text-xl">
            {title}
          </h1>
          {description ? (
            <div className="mt-1 max-w-2xl text-xs leading-relaxed text-ink-subtle sm:text-sm">
              {description}
            </div>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

/** Uses the current path to keep document titles and headings honest. */
export function usePageTitle(title: string): void {
  usePathname();
  React.useEffect(() => {
    document.title = `${title} · Digital Twin`;
  }, [title]);
}

export function useRouterSafe(): ReturnType<typeof useRouter> {
  return useRouter();
}
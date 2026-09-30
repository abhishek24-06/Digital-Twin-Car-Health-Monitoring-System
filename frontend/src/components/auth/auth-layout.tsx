"use client";

import * as React from "react";
import { Activity, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Split-screen auth shell: a brand/marketing panel on large screens and a plain
 * centred form on small ones.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,32rem)]">
      <aside className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between">
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          aria-hidden
          style={{
            backgroundImage:
              "radial-gradient(60% 50% at 20% 10%, color-mix(in oklab, var(--signal-500) 22%, transparent), transparent 70%), radial-gradient(50% 40% at 80% 90%, color-mix(in oklab, var(--color-info) 18%, transparent), transparent 70%)",
          }}
        />
        <div className="relative flex items-center gap-2.5 px-8 py-7">
          <span className="grid size-9 place-items-center rounded-xl bg-signal-500/15 text-signal-400">
            <Activity className="size-4.5" aria-hidden />
          </span>
          <span>
            <span className="block text-sm font-semibold tracking-tight text-ink">
              Digital Twin
            </span>
            <span className="block text-[0.68rem] text-ink-subtle">
              Car health intelligence
            </span>
          </span>
        </div>

        <div className="relative max-w-lg px-8 pb-10">
          <h2 className="text-2xl font-semibold leading-tight tracking-tight text-ink">
            Know what your car needs, before it fails.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-ink-muted">
            Digital Twin scores every vehicle from stored telemetry using a
            deterministic rule engine, then uses retrieval-augmented reasoning to
            explain the result in your own words — with every claim tied back to its
            source.
          </p>
          <ul className="mt-6 space-y-2.5 text-xs text-ink-subtle">
            {[
              "Health score from explainable thresholds, not a black box",
              "AI interpretation labelled separately from measured data",
              "Manufacturer documentation retrieved as cited evidence",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <ArrowRight className="mt-0.5 size-3 shrink-0 text-signal-400" aria-hidden />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <main className="flex flex-col justify-center px-5 py-10 sm:px-10">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-7 flex items-center gap-2.5 lg:hidden">
            <span className="grid size-9 place-items-center rounded-xl bg-signal-500/15 text-signal-400">
              <Activity className="size-4.5" aria-hidden />
            </span>
            <span className="text-sm font-semibold tracking-tight text-ink">
              Digital Twin
            </span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          <p className={cn("mt-1.5 text-sm text-ink-subtle")}>{subtitle}</p>

          <div className="mt-6">{children}</div>

          {footer ? <div className="mt-6 text-xs text-ink-subtle">{footer}</div> : null}
        </div>
      </main>
    </div>
  );
}

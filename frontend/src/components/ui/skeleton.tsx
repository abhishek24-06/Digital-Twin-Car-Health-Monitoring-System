import { cn } from "@/lib/utils";

/**
 * Skeleton primitives.
 *
 * `shimmer` is applied through a pseudo-element (see globals.css) so a single
 * class gives every loading surface the same subtle motion, and the whole thing
 * collapses to a static block under `prefers-reduced-motion`.
 */

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("shimmer rounded-md bg-surface-3/70", className)}
      {...props}
    />
  );
}

export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3", index === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

/** Wraps a group of skeletons with a single, quiet loading announcement. */
export function SkeletonRegion({
  label = "Loading",
  className,
  children,
}: {
  label?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

export function MetricCardSkeleton() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-7 w-20" />
      <Skeleton className="mt-3 h-2.5 w-16" />
    </div>
  );
}

export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      className="rounded-lg border border-line bg-surface-2 p-3"
      style={{ height }}
      aria-hidden
    >
      <Skeleton className="h-full w-full rounded-md" />
    </div>
  );
}

export function TableSkeleton({ rows = 6, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex gap-3">
          {Array.from({ length: columns }, (_, col) => (
            <Skeleton
              key={col}
              className={cn("h-4 flex-1", row === 0 && "h-5")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
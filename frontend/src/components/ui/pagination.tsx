"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Pagination driven by the backend's `PaginatedResponse` envelope
 * (`items`, `page`, `page_size`, `total`).
 */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
  label = "pagination",
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
  label?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / Math.max(pageSize, 1)));
  if (total === 0) return null;

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <nav
      aria-label={label}
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3",
        className,
      )}
    >
      <p className="tabular text-xs text-ink-subtle">
        Showing <span className="text-ink-muted">{from}</span>–
        <span className="text-ink-muted">{to}</span> of{" "}
        <span className="text-ink-muted">{total.toLocaleString()}</span>
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          <ChevronLeft aria-hidden />
          Previous
        </Button>
        <span className="tabular text-xs text-ink-subtle">
          Page {page} of {pageCount}
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount}
        >
          Next
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
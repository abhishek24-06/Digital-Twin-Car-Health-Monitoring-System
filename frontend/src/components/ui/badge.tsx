import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.7rem] font-medium leading-5 whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral:
          "border-line bg-surface-2 text-ink-muted",
        accent:
          "border-[color:color-mix(in_oklab,var(--color-signal-500)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-signal-500)_14%,transparent)] text-signal-300",
        healthy:
          "border-[color:color-mix(in_oklab,var(--color-healthy)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-healthy)_14%,transparent)] text-[color:var(--color-healthy)]",
        attention:
          "border-[color:color-mix(in_oklab,var(--color-attention)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-attention)_14%,transparent)] text-[color:var(--color-attention)]",
        critical:
          "border-[color:color-mix(in_oklab,var(--color-critical)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-critical)_14%,transparent)] text-[color:var(--color-critical)]",
        unknown:
          "border-[color:color-mix(in_oklab,var(--color-unknown)_42%,transparent)] bg-[color:color-mix(in_oklab,var(--color-unknown)_14%,transparent)] text-[color:var(--color-unknown)]",
      },
      size: {
        sm: "text-[0.68rem]",
        md: "",
      },
    },
    defaultVariants: { tone: "neutral", size: "md" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, size, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone, size }), className)} {...props} />
  );
}

export { badgeVariants };
"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md",
    "text-sm font-medium transition-colors",
    "focus-visible:outline-2 focus-visible:outline-offset-2",
    "disabled:pointer-events-none disabled:opacity-55",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        primary:
          "bg-signal-500 text-white shadow-sm hover:bg-signal-400 active:bg-signal-600 focus-visible:outline-signal-400",
        secondary:
          "bg-surface-3 text-ink hover:bg-[color:color-mix(in_oklab,var(--ink)_10%,var(--surface-3))] focus-visible:outline-signal-400",
        outline:
          "border border-line bg-transparent text-ink hover:bg-surface-2 focus-visible:outline-signal-400",
        ghost: "text-ink-muted hover:bg-surface-2 hover:text-ink focus-visible:outline-signal-400",
        danger:
          "bg-[color:var(--color-critical)] text-black hover:brightness-110 focus-visible:outline-[color:var(--color-critical)]",
        link: "text-signal-400 underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-xs [&_svg]:size-3.5",
        md: "h-9 px-4 [&_svg]:size-4",
        lg: "h-11 px-5 text-[0.95rem] [&_svg]:size-4",
        icon: "size-9 [&_svg]:size-4",
        iconSm: "size-8 [&_svg]:size-3.5",
      },
      block: { true: "w-full", false: "" },
    },
    defaultVariants: { variant: "primary", size: "md", block: false },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Shows a spinner and blocks interaction while an action is in flight. */
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { className, variant, size, block, asChild, loading, children, disabled, ...props },
    ref,
  ) {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size, block }), className)}
        disabled={disabled ?? loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? (
          <>
            <Loader2 className="animate-spin" aria-hidden />
            {children}
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);

export { buttonVariants };
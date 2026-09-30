"use client";

import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/utils";

export function Label({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      className={cn(
        "text-xs font-medium text-ink-muted peer-disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & {
    invalid?: boolean;
  }
>(function Input({ className, invalid, type, ...props }, ref) {
  return (
    <input
      ref={ref}
      type={type}
      aria-invalid={invalid || undefined}
      className={cn(
        "h-10 w-full rounded-md border bg-surface-2 px-3 text-sm text-ink",
        "placeholder:text-ink-subtle",
        "transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-signal-400",
        "disabled:cursor-not-allowed disabled:opacity-55",
        invalid
          ? "border-[color:var(--color-critical)]"
          : "border-line hover:border-line-strong",
        className,
      )}
      {...props}
    />
  );
});

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(function Textarea({ className, invalid, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "w-full rounded-md border bg-surface-2 px-3 py-2 text-sm text-ink",
        "placeholder:text-ink-subtle",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-signal-400",
        "disabled:cursor-not-allowed disabled:opacity-55",
        invalid ? "border-[color:var(--color-critical)]" : "border-line",
        className,
      )}
      {...props}
    />
  );
});

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...props }, ref) {
  return (
    <select
      ref={ref}
      className={cn(
        "h-10 w-full cursor-pointer appearance-none rounded-md border border-line bg-surface-2 px-3 pr-8 text-sm text-ink",
        "bg-[image:linear-gradient(45deg,transparent_50%,currentColor_50%),linear-gradient(135deg,currentColor_50%,transparent_50%)]",
        "bg-[position:calc(100%-15px)_calc(50%+2px),calc(100%-10px)_calc(50%+2px)] bg-[size:5px_5px,5px_5px] bg-no-repeat",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-signal-400",
        "disabled:cursor-not-allowed disabled:opacity-55",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
});

/** Field wrapper: label + control + hint/error wired up for screen readers. */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string | undefined;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="text-[color:var(--color-critical)]" aria-hidden>
            {" *"}
          </span>
        ) : null}
      </Label>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            id: htmlFor,
            "aria-describedby": [hintId, errorId].filter(Boolean).join(" ") || undefined,
            "aria-invalid": error ? true : undefined,
          })
        : children}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-ink-subtle">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-[color:var(--color-critical)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
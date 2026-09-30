"use client";

import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Small accessible listbox used where a full Radix Select would be overkill
 * (vehicle picker, metric picker). Radix handles focus management, typeahead
 * roles and keyboard dismissal.
 */

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  description?: string;
  disabled?: boolean;
}

export function SelectMenu<T extends string>({
  value,
  options,
  onChange,
  placeholder = "Select",
  className,
  triggerClassName,
  align = "start",
  label,
}: {
  value: T | null;
  options: ReadonlyArray<SelectOption<T>>;
  onChange: (value: T) => void;
  placeholder?: string;
  className?: string;
  triggerClassName?: string;
  align?: "start" | "end" | "center";
  label?: string;
}) {
  const selected = options.find((option) => option.value === value);

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            "inline-flex w-full items-center justify-between gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-left text-sm text-ink",
            "transition-colors hover:border-line-strong",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
            "data-[state=open]:border-signal-500",
            triggerClassName,
            className,
          )}
        >
          <span className={cn("truncate", !selected && "text-ink-subtle")}>
            {selected?.label ?? placeholder}
          </span>
          <svg
            className="size-3.5 shrink-0 text-ink-subtle"
            viewBox="0 0 12 12"
            aria-hidden
          >
            <path
              d="M2.5 4.5 6 8l3.5-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align={align}
          sideOffset={6}
          className="z-50 max-h-72 w-[min(20rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-[var(--shadow-pop)] scrollbar-slim"
        >
          {options.length === 0 ? (
            <p className="px-3 py-2 text-xs text-ink-subtle">No options</p>
          ) : null}
          {options.map((option) => (
            <DropdownMenu.Item
              key={option.value}
              disabled={option.disabled}
              onSelect={() => onChange(option.value)}
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-md px-2.5 py-2 text-sm text-ink outline-none",
                "focus:bg-surface-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
              )}
            >
              <Check
                className={cn(
                  "mt-0.5 size-3.5 shrink-0 text-signal-400",
                  option.value !== value && "invisible",
                )}
                aria-hidden
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{option.label}</span>
                {option.description ? (
                  <span className="block truncate text-xs text-ink-subtle">
                    {option.description}
                  </span>
                ) : null}
              </span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** Segmented control for small, mutually exclusive option sets. */
export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  className,
  ariaLabel,
}: {
  value: T;
  options: ReadonlyArray<SelectOption<T>>;
  onChange: (value: T) => void;
  className?: string;
  ariaLabel: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={isActive}
            title={option.description ?? option.label}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
              isActive
                ? "bg-surface-3 text-ink shadow-[var(--shadow-panel)]"
                : "text-ink-subtle hover:text-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(function TabsList({ className, ...props }, ref) {
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1 overflow-x-auto rounded-lg border border-line bg-surface-2 p-1",
        "scrollbar-slim",
        className,
      )}
      {...props}
    />
  );
});

export const TabsTrigger = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(function TabsTrigger({ className, ...props }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium text-ink-subtle",
        "transition-colors hover:text-ink",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
        "data-[state=active]:bg-surface-3 data-[state=active]:text-ink data-[state=active]:shadow-[var(--shadow-panel)]",
        "[&_svg]:size-3.5 [&_svg]:shrink-0",
        className,
      )}
      {...props}
    />
  );
});

export const TabsContent = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(function TabsContent({ className, ...props }, ref) {
  return (
    <TabsPrimitive.Content
      ref={ref}
      className={cn("mt-4 focus-visible:outline-none", className)}
      {...props}
    />
  );
});

/** Link-styled tabs for nested routes (keeps real URLs + keyboard semantics). */
export const TabsLinkList = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    items: Array<{ href: string; label: string; icon?: React.ReactNode }>;
    activeHref: string;
  }
>(function TabsLinkList({ items, activeHref, className, ...props }, ref) {
  return (
    <div
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1 overflow-x-auto rounded-lg border border-line bg-surface-2 p-1 scrollbar-slim",
        className,
      )}
      role="tablist"
      aria-label="Vehicle sections"
      {...props}
    >
      {items.map((item) => {
        const isActive =
          activeHref === item.href || activeHref.startsWith(`${item.href}/`);
        return (
          <a
            key={item.href}
            href={item.href}
            role="tab"
            aria-selected={isActive}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400",
              isActive
                ? "bg-surface-3 text-ink shadow-[var(--shadow-panel)]"
                : "text-ink-subtle hover:text-ink",
            )}
          >
            {item.icon}
            {item.label}
          </a>
        );
      })}
    </div>
  );
});
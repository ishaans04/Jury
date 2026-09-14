import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A plain native `<select>` styled to match the rest of the kit, rather
 * than pulling in the full Radix `Select` primitive. This app has no
 * multi-select, search, or virtualization needs anywhere — every use is a
 * short enum (chair, axis value, archetype) — so the native element is the
 * simpler and more accessible choice.
 */
export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";

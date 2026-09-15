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
        "flex h-10 w-full px-3 rounded-2xl border border-[#E2D8C6] bg-white/80 text-sm text-[#2A2620] placeholder:text-[#A79E8F] transition-shadow focus-visible:border-[#5B5BF7]/50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#5B5BF7]/15 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";

import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-11 w-full px-3.5 py-2 rounded-2xl border border-[#E2D8C6] bg-white/80 text-sm text-[#2A2620] placeholder:text-[#A79E8F] transition-shadow focus-visible:border-[#5B5BF7]/50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#5B5BF7]/15 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

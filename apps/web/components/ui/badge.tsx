import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "border-transparent bg-[#2A2620] text-white",
      secondary: "border-transparent bg-[#F1EADC] text-[#5A5348]",
      outline: "border-[#E2D8C6] bg-white/60 text-[#5A5348]",
      warning: "border-transparent bg-amber-100 text-amber-800",
      success: "border-transparent bg-emerald-100 text-emerald-800",
      destructive: "border-transparent bg-rose-100 text-rose-800",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

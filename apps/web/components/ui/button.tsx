import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-all duration-200 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#5B5BF7]/30 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-r from-[#5B5BF7] to-[#8B63F5] text-white shadow-[0_10px_24px_-10px_rgba(91,91,247,0.7)] hover:-translate-y-0.5 hover:shadow-[0_14px_30px_-10px_rgba(91,91,247,0.8)]",
        dark: "bg-[#141A2E] text-white shadow-[0_10px_24px_-12px_rgba(20,26,46,0.7)] hover:-translate-y-0.5 hover:bg-[#232A42]",
        outline: "border border-[#E2D8C6] bg-white/80 text-[#2A2620] backdrop-blur hover:bg-white",
        ghost: "text-[#2A2620] hover:bg-white/70",
        destructive: "bg-red-600 text-white hover:bg-red-700",
      },
      size: {
        default: "h-11 px-5",
        sm: "h-9 px-4 text-xs",
        lg: "h-14 px-8 text-base",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";

import Link from "next/link";

import { cn } from "@/lib/utils";

export function Logo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link href={href} className={cn("inline-flex items-center rounded-full", className)}>
      <span className="font-display text-2xl leading-none tracking-tight text-[#2A2620]">The Jury</span>
    </Link>
  );
}

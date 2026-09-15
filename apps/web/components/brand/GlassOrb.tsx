import { cn } from "@/lib/utils";

/** The liquid-glass orb that turns in the middle of the table while the
 * jury deliberates. */
export function GlassOrb({ active, className }: { active: boolean; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "orb pointer-events-none transition-all duration-700 ease-out",
        active ? "scale-100 opacity-100" : "scale-50 opacity-0",
        className,
      )}
    >
      <span className="orb-glow" />
      <span className="orb-liquid" />
      <span className="orb-glass" />
      <span className="sr-only">{active ? "The Jury is deliberating" : ""}</span>
    </div>
  );
}

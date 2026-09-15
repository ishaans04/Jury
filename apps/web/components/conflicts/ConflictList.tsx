import type { Conflict, ConflictKind, ConflictStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

/** F9: `scope_gap` is a distinct kind from a contradiction (`chair_vs_chair`
 * / `founder_vs_world`) and must read as a gap, not as disagreement. */
const KIND_LABELS: Record<ConflictKind, string> = {
  founder_vs_world: "Founder vs. world",
  chair_vs_chair: "Chair vs. chair",
  no_evidence: "No evidence",
  scope_gap: "Scope gap",
};

const STATUS_VARIANT: Record<ConflictStatus, "warning" | "success" | "secondary" | "destructive"> = {
  open: "warning",
  resolved: "success",
  conceded: "secondary",
  unresolvable: "destructive",
};

/**
 * Conflicts labelled by kind (PRD §22's 2:40 beat calls out
 * `founder_vs_world` distinctly). An unresolved conflict renders as `open`
 * rather than being filtered out — hiding an open conflict would be the
 * one failure mode PRD §22 exists to prevent.
 */
export function ConflictList({ conflicts }: { conflicts: Conflict[] }) {
  if (conflicts.length === 0) {
    return <p className="text-sm text-[#6B645A]">No conflicts recorded for this run.</p>;
  }

  return (
    <div className="flex flex-col gap-2" data-testid="conflict-list">
      {conflicts.map((conflict) => (
        <div
          key={conflict.id}
          className="flex flex-col gap-1 rounded-2xl border border-[#EFE7D8] bg-white/80 p-3 text-sm"
          data-testid="conflict-row"
          data-kind={conflict.kind}
        >
          <div className="flex items-center justify-between gap-2">
            <Badge variant="outline">{KIND_LABELS[conflict.kind]}</Badge>
            <Badge variant={STATUS_VARIANT[conflict.status]}>{conflict.status}</Badge>
          </div>
          <span className="text-xs text-[#6B645A]">Rule {conflict.rule} · {conflict.severity} severity</span>
          {conflict.resolution && <p className="text-xs text-[#5A5348]">{conflict.resolution}</p>}
        </div>
      ))}
    </div>
  );
}

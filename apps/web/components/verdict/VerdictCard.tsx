import type { Verdict } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBreakdown } from "./ConfidenceBreakdown";
import { ConflictList } from "@/components/conflicts/ConflictList";
import type { Conflict } from "@/lib/types";

const DECISION_VARIANT = {
  PROCEED: "success",
  PIVOT: "warning",
  STOP: "destructive",
  HUNG_JURY: "secondary",
} as const;

/**
 * A friction row carries only what `build_friction` (apps/api/jury/graph/
 * nodes/jury.py) actually returns — kind/rule/status plus an optional
 * resolution — so this renders straight off `verdict.friction` rather than
 * needing the full `Conflict` rows it summarizes.
 */
function frictionAsConflicts(verdict: Verdict): Conflict[] {
  return verdict.friction.map((f, i) => ({
    id: `friction-${i}`,
    project_id: verdict.project_id,
    run_id: verdict.run_id,
    assumption_id: "",
    kind: f.kind,
    left_ref: {},
    right_ref: null,
    rule: f.rule,
    severity: "high",
    status: f.status,
    resolution: f.resolution ?? null,
    created_at: verdict.created_at,
  }));
}

/**
 * The decision card: PROCEED/PIVOT/STOP/HUNG_JURY, its confidence
 * decomposition (never bare — see `ConfidenceBreakdown`), the friction
 * summary naming the conflicts that mattered (PRD §7.8), and the gate
 * condition that fired when one did.
 */
export function VerdictCard({ verdict }: { verdict: Verdict }) {
  return (
    <Card data-testid="verdict-card">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Verdict</CardTitle>
          <Badge variant={DECISION_VARIANT[verdict.decision]} data-testid="verdict-decision">
            {verdict.decision}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ConfidenceBreakdown total={verdict.evidence_confidence} components={verdict.components} />

        {verdict.gate_triggered && (
          <p className="text-xs text-[#5A5348]" data-testid="gate-triggered">
            Gate condition: <span className="font-mono">{verdict.gate_triggered}</span>
          </p>
        )}

        <p className="text-sm text-[#3D3830]">{verdict.rationale}</p>

        {verdict.friction.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-[#6B645A]">
              Friction — conflicts that mattered
            </span>
            <ConflictList conflicts={frictionAsConflicts(verdict)} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

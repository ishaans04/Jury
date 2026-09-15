import type { Experiment } from "@/lib/types";
import { EXPERIMENT_METHOD_LABELS } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * One experiment rendered as a card. P9: a pre-registered kill criterion is
 * non-null on every experiment row, and this card renders it
 * unconditionally — including a visibly-wrong fallback if a row somehow
 * arrives with it blank, rather than silently omitting the row (mirrors
 * `EvidenceCard`'s "source unavailable" treatment for a missing FK join).
 * Cost and duration are likewise always shown. `limitation` only renders
 * for `documented_proxy` (spec §26.6: retention is not testable in 30
 * days, so the proxy's caveat is stated in the product rather than papered
 * over).
 */
export function ExperimentCard({ experiment }: { experiment: Experiment }) {
  const hasKillCriterion = experiment.kill_criterion.trim().length > 0;

  return (
    <Card data-testid="experiment-card">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>{EXPERIMENT_METHOD_LABELS[experiment.method]}</CardTitle>
          {experiment.target_variable && <Badge variant="outline">{experiment.target_variable}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm text-[#3D3830]">
        <p>{experiment.instructions}</p>

        <div className="flex gap-4 text-xs text-[#6B645A]">
          <span data-testid="experiment-cost">
            Cost: {experiment.est_cost !== null ? experiment.est_cost : "—"}
          </span>
          <span data-testid="experiment-duration">
            Duration: {experiment.est_days !== null ? `${experiment.est_days}d` : "—"}
          </span>
        </div>

        <p
          className={
            hasKillCriterion
              ? "rounded bg-amber-50 p-2 text-xs font-medium text-amber-800"
              : "rounded bg-red-50 p-2 text-xs font-medium text-red-700"
          }
          data-testid="experiment-kill-criterion"
        >
          {hasKillCriterion ? experiment.kill_criterion : "No kill criterion recorded — this row must not ship."}
        </p>

        {experiment.method === "documented_proxy" && experiment.limitation && (
          <p className="rounded bg-[#F7F1E6] p-2 text-xs text-[#5A5348]" data-testid="experiment-limitation">
            {experiment.limitation}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

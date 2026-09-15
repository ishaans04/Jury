import type { Experiment, Verdict } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ExperimentCard } from "@/components/experiments/ExperimentCard";
import { ConfidenceBreakdown } from "./ConfidenceBreakdown";

/**
 * A hung jury rendered as a refusal with next steps (PRD §18: "it must be
 * presented as a feature rather than a bug"), never as an error state.
 * Deliberately avoids failure-shaped language ("error", "failed") — the
 * jury is telling the founder the evidence doesn't support a call yet, and
 * naming the three cheapest experiments that would break the deadlock
 * (PRD §9.4) is the whole point of this screen.
 */
export function HungJury({ verdict, experiments }: { verdict: Verdict; experiments: Experiment[] }) {
  return (
    <Card data-testid="hung-jury">
      <CardHeader>
        <CardTitle>Hung jury</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-[#3D3830]">
          There is insufficient evidence to rule on this pitch yet. The jury is refusing to call PROCEED,
          PIVOT, or STOP until one of the experiments below moves the evidence.
        </p>

        {verdict.gate_triggered && (
          <p className="text-xs text-[#5A5348]" data-testid="gate-triggered">
            Gate condition: <span className="font-mono">{verdict.gate_triggered}</span>
          </p>
        )}

        <ConfidenceBreakdown total={verdict.evidence_confidence} components={verdict.components} />

        <div className="flex flex-col gap-3">
          <span className="text-xs font-medium uppercase tracking-wide text-[#6B645A]">
            Three cheapest experiments to break the deadlock
          </span>
          {experiments.length === 0 ? (
            <p className="text-sm text-[#6B645A]" data-testid="hung-jury-no-experiments">
              No experiments are planned yet. They come from the numbers you assert in the hearing, so
              add your price, costs or conversion figures as assumptions and run The Jury again.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {experiments.map((experiment) => (
                <ExperimentCard key={experiment.id ?? experiment.assumption_id} experiment={experiment} />
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

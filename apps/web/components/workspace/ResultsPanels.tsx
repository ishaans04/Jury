import type { SupabaseClient } from "@supabase/supabase-js";

import type { RunOut } from "@/lib/api";
import type {
  Chair,
  Conflict,
  EvidenceItem,
  Experiment,
  ModelRun,
  PositionDeltaRecord,
  Verdict,
} from "@/lib/types";
import { Boardroom } from "@/components/boardroom/Boardroom";
import { CrossExamStream } from "@/components/hearing/CrossExamStream";
import { ConflictList } from "@/components/conflicts/ConflictList";
import { PositionDelta } from "@/components/conflicts/PositionDelta";
import { TornadoChart } from "@/components/economics/TornadoChart";
import { Breakpoints } from "@/components/economics/Breakpoints";
import { VerdictCard } from "@/components/verdict/VerdictCard";
import { HungJury } from "@/components/verdict/HungJury";
import { ExperimentCard } from "@/components/experiments/ExperimentCard";
import { Badge } from "@/components/ui/badge";

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-10 text-center text-sm text-[#6B645A]">{children}</p>;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-[#2A2620]">{children}</h3>;
}

/** Cheapest-first: the backend's `priority` is the experiment ranking. */
export function topExperiments(experiments: Experiment[], n = 3): Experiment[] {
  return [...experiments].sort((a, b) => a.priority - b.priority).slice(0, n);
}

export function VerdictPanel({ verdict, experiments }: { verdict: Verdict | null; experiments: Experiment[] }) {
  if (!verdict) return <Empty>The Chairman hasn&apos;t ruled yet. The verdict appears here once deliberation ends.</Empty>;
  if (verdict.decision === "HUNG_JURY") {
    return <HungJury verdict={verdict} experiments={topExperiments(experiments)} />;
  }
  return (
    <div className="flex flex-col gap-6">
      <VerdictCard verdict={verdict} />
      {experiments.length > 0 && (
        <div className="flex flex-col gap-3">
          <SectionTitle>Recommended experiments</SectionTitle>
          <div className="grid gap-3 md:grid-cols-3">
            {topExperiments(experiments).map((e) => (
              <ExperimentCard key={e.id ?? e.assumption_id} experiment={e} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function EvidencePanel({
  supabase,
  runId,
  evidence,
  partialChairs,
}: {
  supabase: SupabaseClient;
  runId: string;
  evidence: EvidenceItem[];
  partialChairs: Chair[];
}) {
  return <Boardroom supabase={supabase} runId={runId} evidence={evidence} partialChairs={partialChairs} />;
}

export function CrossExamPanel({
  run,
  accessToken,
  conflicts,
  deltas,
}: {
  run: RunOut;
  accessToken: string;
  conflicts: Conflict[];
  deltas: PositionDeltaRecord[];
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="flex flex-col gap-3">
        {run.status === "cross_exam" && (
          <>
            <SectionTitle>Live cross-examination</SectionTitle>
            <CrossExamStream runId={run.id} accessToken={accessToken} />
          </>
        )}
        <SectionTitle>Conflicts</SectionTitle>
        <ConflictList conflicts={conflicts} />
      </div>
      <div className="flex flex-col gap-3">
        <SectionTitle>Position shifts</SectionTitle>
        {deltas.length === 0 ? (
          <p className="text-sm text-[#6B645A]">No chair has changed its stance yet.</p>
        ) : (
          deltas.map((d) => <PositionDelta key={d.id} delta={d} />)
        )}
      </div>
    </div>
  );
}

const OUTPUT_LABELS: { key: keyof ModelRun["outputs"]; label: string }[] = [
  { key: "contribution_margin", label: "Contribution margin" },
  { key: "ltv", label: "LTV" },
  { key: "ltv_cac", label: "LTV / CAC" },
  { key: "payback_months", label: "Payback (months)" },
  { key: "breakeven_volume_monthly", label: "Break-even volume / mo" },
];

export function EconomicsPanel({ modelRun }: { modelRun: ModelRun | null }) {
  if (!modelRun) return <Empty>The Economics chair hasn&apos;t solved the model for this run yet.</Empty>;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={modelRun.viable ? "success" : "destructive"}>{modelRun.viable ? "viable" : "not viable"}</Badge>
        <span className="text-xs text-[#6B645A]">template {modelRun.template_key}</span>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {OUTPUT_LABELS.map(({ key, label }) => {
          const v = modelRun.outputs[key];
          return (
            <div key={key} className="shadow-soft rounded-2xl border border-white/80 bg-white/80 p-4">
              <dt className="text-xs text-[#6B645A]">{label}</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums text-[#2A2620]">
                {v === null || v === undefined ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </dd>
            </div>
          );
        })}
      </dl>
      <div className="flex flex-col gap-3">
        <SectionTitle>Sensitivity — what moves the outcome most</SectionTitle>
        <TornadoChart sensitivity={modelRun.sensitivity} />
      </div>
      {modelRun.breakpoints.length > 0 && (
        <div className="flex flex-col gap-3">
          <SectionTitle>Breakpoints</SectionTitle>
          <Breakpoints breakpoints={modelRun.breakpoints} />
        </div>
      )}
    </div>
  );
}

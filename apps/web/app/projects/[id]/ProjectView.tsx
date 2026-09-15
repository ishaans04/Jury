"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { api, type ProjectOut, type RunOut } from "@/lib/api";
import type { Archetype, Chair, CoverageGap, HearingAssumption } from "@/lib/types";
import { SEATS, type Seat } from "@/lib/chairs";
import { useEvidenceStream } from "@/hooks/useEvidenceStream";
import { useResultsData } from "@/hooks/useResultsData";
import { Hearing } from "@/components/hearing/Hearing";
import { ChairTable } from "@/components/brand/ChairTable";
import { Button } from "@/components/ui/button";
import { LedgerPanel } from "@/components/ledger/LedgerPanel";
import {
  CrossExamPanel,
  EconomicsPanel,
  EvidencePanel,
  VerdictPanel,
} from "@/components/workspace/ResultsPanels";
import { cn } from "@/lib/utils";

interface ProjectViewProps {
  project: ProjectOut;
  initialRun: RunOut | null;
  accessToken: string;
}

const POLL_MS = 2000;
const TERMINAL_STATUSES = new Set(["complete", "failed"]);
const DELIBERATING = new Set(["pending", "investigating", "cross_exam", "deciding"]);

const STAGES: { status: RunOut["status"]; label: string }[] = [
  { status: "hearing", label: "Hearing" },
  { status: "investigating", label: "Investigation" },
  { status: "cross_exam", label: "Cross-exam" },
  { status: "deciding", label: "Deliberation" },
  { status: "complete", label: "Verdict" },
];

type Tab = "verdict" | "evidence" | "cross" | "economics" | "ledger";
const TABS: { key: Tab; label: string }[] = [
  { key: "verdict", label: "Verdict" },
  { key: "evidence", label: "Evidence" },
  { key: "cross", label: "Cross-exam" },
  { key: "economics", label: "Economics" },
  { key: "ledger", label: "Living ledger" },
];

function confidenceCacheKey(projectId: string) {
  return `jury:archetype_confidence:${projectId}`;
}

function defaultTab(status: RunOut["status"] | undefined): Tab {
  if (status === "complete") return "verdict";
  if (status === "cross_exam") return "cross";
  return "evidence";
}

/**
 * The boardroom workspace for a single project. The five chairs sit at the
 * table on the stage (the liquid-glass orb turns while the run deliberates);
 * below it, the dock switches between "no run yet", the hearing, and the
 * results tabs based on the run's `status`. Polls `GET /runs/{id}` while
 * the run is non-terminal — there is no push channel for run status itself.
 */
export function ProjectView({ project, initialRun, accessToken }: ProjectViewProps) {
  const searchParams = useSearchParams();
  const supabase = useMemo(() => createClient(), []);
  const [run, setRun] = useState<RunOut | null>(initialRun);
  const [tab, setTab] = useState<Tab>(defaultTab(initialRun?.status));
  const [activeSeat, setActiveSeat] = useState<Seat | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [starting, setStarting] = useState(false);
  const [hearingPayload, setHearingPayload] = useState<{
    assumptions: HearingAssumption[];
    coverageGaps: CoverageGap[];
  } | null>(null);

  const queryConfidence = searchParams.get("ac");
  const [archetypeConfidence] = useState<number | null>(() => {
    if (queryConfidence) return Number(queryConfidence);
    if (typeof window === "undefined") return null;
    const cached = window.localStorage.getItem(confidenceCacheKey(project.id));
    return cached ? Number(cached) : null;
  });

  useEffect(() => {
    if (queryConfidence) {
      window.localStorage.setItem(confidenceCacheKey(project.id), queryConfidence);
    }
  }, [queryConfidence, project.id]);

  // Poll run status until it reaches a terminal state.
  useEffect(() => {
    if (!run || TERMINAL_STATUSES.has(run.status)) return;
    const interval = setInterval(async () => {
      try {
        const updated = await api.getRun(accessToken, run.id);
        setRun((prev) => {
          if (prev && prev.status !== updated.status) setTab(defaultTab(updated.status));
          return updated;
        });
      } catch {
        // transient — next tick retries
      }
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [run, accessToken]);

  // Once the run is in "hearing", load the interrupt payload from the run's
  // own trace (the last `interrupt` event carries exactly what the hearing
  // node paused with: `assumptions` and `coverage_gaps`).
  useEffect(() => {
    if (!run || run.status !== "hearing") return;
    let cancelled = false;
    api.getRunEvents(accessToken, run.id).then((events) => {
      if (cancelled) return;
      const interruptEvents = events.filter((e) => e.event === "interrupt");
      const latest = interruptEvents[interruptEvents.length - 1];
      if (latest?.detail) {
        setHearingPayload({
          assumptions: (latest.detail.assumptions as HearingAssumption[]) ?? [],
          coverageGaps: (latest.detail.coverage_gaps as CoverageGap[]) ?? [],
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [run, accessToken]);

  const postHearing = !!run && run.status !== "pending" && run.status !== "hearing";
  const { evidence, partialChairs } = useEvidenceStream(supabase, postHearing ? run.id : null);
  const results = useResultsData(supabase, postHearing ? run.id : null, project.id, `${run?.status}:${refreshKey}`);

  const counts = useMemo(() => {
    const out: Partial<Record<Chair, number>> = {};
    for (const item of evidence) out[item.chair] = (out[item.chair] ?? 0) + 1;
    return out;
  }, [evidence]);

  const thinking = !!run && DELIBERATING.has(run.status);

  function selectSeat(seat: Seat) {
    setActiveSeat(seat);
    if (!postHearing) return;
    if (seat === "chairman") {
      setTab("verdict");
      return;
    }
    const chair = seat;
    setTab("evidence");
    requestAnimationFrame(() =>
      document.getElementById(`chair-col-${chair}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
    );
  }

  async function startRun() {
    setStarting(true);
    try {
      const { run_id } = await api.startRun(accessToken, project.id, "initial");
      setRun(await api.getRun(accessToken, run_id));
    } catch {
      setStarting(false);
    }
  }

  const stageIndex = run ? STAGES.findIndex((s) => s.status === run.status) : -1;

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Boardroom" className="relative flex flex-col items-center gap-4">
        <ol className="flex flex-wrap items-center justify-center gap-1.5" aria-label="Run progress">
          {STAGES.map((s, i) => {
            const done = stageIndex > i || run?.status === "complete";
            const current = stageIndex === i;
            return (
              <li
                key={s.status}
                aria-current={current ? "step" : undefined}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition-all",
                  current
                    ? "bg-[#2A2620] text-white shadow-md"
                    : done
                      ? "bg-[#EEF0FF] text-[#4B4BD6]"
                      : "glass-chip text-[#9A9183]",
                )}
              >
                {s.label}
              </li>
            );
          })}
          {run?.status === "failed" && (
            <li className="rounded-full bg-rose-100 px-3 py-1 text-xs font-medium text-rose-800">Run stopped</li>
          )}
        </ol>

        <ChairTable
          thinking={thinking}
          counts={counts}
          partial={partialChairs}
          activeSeat={activeSeat}
          onSelect={selectSeat}
          selectLabel={(s) =>
            s === "chairman" ? "The Chairman — open the verdict" : `${SEATS[s].name} chair — ${counts[s] ?? 0} evidence items`
          }
          className="max-w-2xl"
        />
      </section>

      <section className="glass rounded-[2rem] p-3 sm:p-6" aria-label="Case file">
        {!run && (
          <div className="flex flex-col items-center gap-4 py-10 text-center">
            <p className="text-sm text-[#6B645A]">No run has been started for this project yet.</p>
            <Button onClick={startRun} disabled={starting}>
              {starting ? "Convening…" : "Convene The Jury"}
            </Button>
          </div>
        )}

        {run?.status === "pending" && (
          <p className="py-10 text-center text-sm text-[#6B645A]">Starting the run…</p>
        )}

        {run?.status === "hearing" &&
          (hearingPayload ? (
            <Hearing
              runId={run.id}
              projectId={project.id}
              accessToken={accessToken}
              archetype={project.archetype as Archetype | null}
              archetypeConfidence={archetypeConfidence}
              initialAssumptions={hearingPayload.assumptions}
              coverageGaps={hearingPayload.coverageGaps}
              onConfirmed={() => {
                setRun({ ...run, status: "investigating" });
                setTab("evidence");
              }}
            />
          ) : (
            <p className="py-10 text-center text-sm text-[#6B645A]">Loading the hearing…</p>
          ))}

        {postHearing && (
          <div className="flex flex-col gap-5">
            <div
              role="tablist"
              aria-label="Results"
              className="-mx-1 flex gap-1 overflow-x-auto rounded-full bg-[#EFE6D6]/70 p-1"
            >
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  id={`tab-${t.key}`}
                  aria-selected={tab === t.key}
                  aria-controls={`panel-${t.key}`}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#5B5BF7]/25",
                    tab === t.key ? "bg-white text-[#2A2620] shadow-sm" : "text-[#6B645A] hover:text-[#2A2620]",
                  )}
                >
                  {t.label}
                </button>
              ))}
              <Link
                href={`/projects/${project.id}/trace?run=${run.id}`}
                className="shrink-0 rounded-full px-4 py-2 text-sm font-medium text-[#6B645A] hover:text-[#2A2620]"
              >
                Trace ↗
              </Link>
            </div>

            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} key={tab} className="rise">
              {tab === "verdict" && <VerdictPanel verdict={results.verdict} experiments={results.experiments} />}
              {tab === "evidence" && (
                <EvidencePanel supabase={supabase} runId={run.id} evidence={evidence} partialChairs={partialChairs} />
              )}
              {tab === "cross" && (
                <CrossExamPanel
                  run={run}
                  accessToken={accessToken}
                  conflicts={results.conflicts}
                  deltas={results.deltas}
                />
              )}
              {tab === "economics" && <EconomicsPanel modelRun={results.modelRun} />}
              {tab === "ledger" && (
                <LedgerPanel
                  projectId={project.id}
                  accessToken={accessToken}
                  experiments={results.experiments}
                  onLogged={() => setRefreshKey((k) => k + 1)}
                />
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

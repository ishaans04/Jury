"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { api, type ProjectOut, type RunOut } from "@/lib/api";
import type { Archetype, CoverageGap, HearingAssumption } from "@/lib/types";
import { Hearing } from "@/components/hearing/Hearing";
import { Boardroom } from "@/components/boardroom/Boardroom";

interface ProjectViewProps {
  project: ProjectOut;
  initialRun: RunOut | null;
  accessToken: string;
}

const POLL_MS = 2000;
const TERMINAL_STATUSES = new Set(["complete", "failed"]);

function confidenceCacheKey(projectId: string) {
  return `jury:archetype_confidence:${projectId}`;
}

/**
 * Owns the switch between "no run yet", the hearing, and the boardroom for
 * a single project, based on the run's `status` (PRD §13's `runs.status`
 * enum). Polls `GET /runs/{id}` while the run is in a non-terminal state —
 * there is no push channel for run status itself, only for the ledger rows
 * the boardroom renders.
 */
export function ProjectView({ project, initialRun, accessToken }: ProjectViewProps) {
  const searchParams = useSearchParams();
  const [run, setRun] = useState<RunOut | null>(initialRun);
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

  // Poll run status until it reaches a terminal state or the hearing.
  useEffect(() => {
    if (!run || TERMINAL_STATUSES.has(run.status)) return;
    const interval = setInterval(async () => {
      try {
        const updated = await api.getRun(accessToken, run.id);
        setRun(updated);
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

  if (!run) {
    return (
      <p className="py-12 text-center text-sm text-slate-500">
        No run has been started for this project yet.
      </p>
    );
  }

  if (run.status === "pending") {
    return <p className="py-12 text-center text-sm text-slate-500">Starting the run…</p>;
  }

  if (run.status === "hearing") {
    if (!hearingPayload) {
      return <p className="py-12 text-center text-sm text-slate-500">Loading the hearing…</p>;
    }
    return (
      <Hearing
        runId={run.id}
        accessToken={accessToken}
        archetype={project.archetype as Archetype | null}
        archetypeConfidence={archetypeConfidence}
        initialAssumptions={hearingPayload.assumptions}
        coverageGaps={hearingPayload.coverageGaps}
        onConfirmed={() => setRun({ ...run, status: "investigating" })}
      />
    );
  }

  // Every post-hearing status (investigating/cross_exam/deciding/complete/
  // failed) renders the live boardroom — it has no separate "done" view
  // because the ledger rows it already wrote simply stop growing.
  return <Boardroom supabase={createClient()} runId={run.id} />;
}

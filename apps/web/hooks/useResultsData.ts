"use client";

import { useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";

import type {
  Conflict,
  Experiment,
  ModelRun,
  PositionDeltaRecord,
  SensitivityEntry,
  SourceRef,
  Verdict,
} from "@/lib/types";

interface ResultsData {
  verdict: Verdict | null;
  modelRun: ModelRun | null;
  conflicts: Conflict[];
  deltas: PositionDeltaRecord[];
  experiments: Experiment[];
  loading: boolean;
}

/** Resolves a `source_id` recorded on an evidence-backed economics
 * parameter against `sources`, so `TornadoChart` can link straight to the
 * citation — `SensitivityEntry` itself only carries `provenance`, not a
 * source (`jury.schemas.economics.SensitivityEntry`). */
async function resolveSensitivitySources(
  supabase: SupabaseClient,
  modelRun: ModelRun,
): Promise<SensitivityEntry[]> {
  const sourceIds = Object.values(modelRun.parameters ?? {})
    .map((p) => p.source_id)
    .filter((id): id is string => Boolean(id));

  let sourcesById = new Map<string, SourceRef>();
  if (sourceIds.length > 0) {
    const { data } = await supabase.from("sources").select("*").in("id", sourceIds);
    sourcesById = new Map(((data as SourceRef[] | null) ?? []).map((s) => [s.id, s]));
  }

  return (modelRun.sensitivity ?? []).map((entry) => {
    const param = modelRun.parameters?.[entry.variable];
    const source = param?.source_id ? (sourcesById.get(param.source_id) ?? null) : null;
    return { ...entry, source };
  });
}

/**
 * Reads for the post-hearing results view (verdict, economics, conflicts,
 * position deltas, experiments) — all direct through `supabase-js` under
 * RLS, per PRD §13: FastAPI owns no "read the ledger" routes for these
 * tables. Fetched once per `runId`/`projectId`; the founder revisits this
 * page rather than watching it update live, unlike the boardroom.
 */
export function useResultsData(
  supabase: SupabaseClient,
  runId: string | null,
  projectId: string | null,
  /** Changing this re-reads everything (run status moved, a result was logged). */
  refreshKey?: string | number,
): ResultsData {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [modelRun, setModelRun] = useState<ModelRun | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [deltas, setDeltas] = useState<PositionDeltaRecord[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId || !projectId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);

      const [verdictRes, modelRunRes, conflictsRes, experimentsRes] = await Promise.all([
        supabase.from("verdicts").select("*").eq("run_id", runId).order("created_at", { ascending: false }).limit(1),
        supabase.from("model_runs").select("*").eq("run_id", runId).order("created_at", { ascending: false }).limit(1),
        supabase.from("conflicts").select("*").eq("run_id", runId),
        supabase.from("experiments").select("*").eq("project_id", projectId),
      ]);
      if (cancelled) return;

      const verdictRow = (verdictRes.data?.[0] as Verdict | undefined) ?? null;
      const modelRunRow = (modelRunRes.data?.[0] as ModelRun | undefined) ?? null;
      const conflictRows = (conflictsRes.data as Conflict[] | null) ?? [];
      const experimentRows = (experimentsRes.data as Experiment[] | null) ?? [];

      let deltaRows: PositionDeltaRecord[] = [];
      const conflictIds = conflictRows.map((c) => c.id);
      if (conflictIds.length > 0) {
        const { data } = await supabase.from("position_deltas").select("*").in("conflict_id", conflictIds);
        deltaRows = (data as PositionDeltaRecord[] | null) ?? [];
      }
      if (cancelled) return;

      if (modelRunRow) {
        modelRunRow.sensitivity = await resolveSensitivitySources(supabase, modelRunRow);
      }
      if (cancelled) return;

      setVerdict(verdictRow);
      setModelRun(modelRunRow);
      setConflicts(conflictRows);
      setDeltas(deltaRows);
      setExperiments(experimentRows);
      setLoading(false);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [supabase, runId, projectId, refreshKey]);

  return { verdict, modelRun, conflicts, deltas, experiments, loading };
}

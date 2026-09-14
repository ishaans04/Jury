"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RealtimeChannel, SupabaseClient } from "@supabase/supabase-js";

import type { Chair, EvidenceItem } from "@/lib/types";

interface UseEvidenceStreamResult {
  evidence: EvidenceItem[];
  partialChairs: Chair[];
  loading: boolean;
  refetch: () => Promise<void>;
}

/**
 * Live boardroom data (F8, PRD §10.2, §18). There is no separate narration
 * channel: an initial `select` populates the board, then a
 * `postgres_changes` INSERT subscription appends new rows as chairs write
 * them. On every (re)subscribe — including the first one and any
 * reconnect after a dropped socket — this refetches the full set rather
 * than trusting accumulated INSERT events, because "state is in Postgres,
 * not in the socket" (PRD §18): a client that trusted the socket across a
 * drop could silently miss rows written while it was disconnected.
 *
 * `partialChairs` is derived from `run_events` error rows for a
 * `chair:<name>` node (see `apps/api/jury/graph/nodes/investigate.py`) —
 * the one signal of chair degradation the schema actually exposes to a
 * direct `supabase-js` reader today. A chair that goes `partial` via
 * budget exhaustion rather than a caught exception (`ChairResult.partial`
 * set without ever raising) emits no distinguishing `run_events` row, so
 * that path is NOT observable from this hook — see the batch report for
 * why this wasn't worked around by touching `apps/api`.
 */
export function useEvidenceStream(
  supabase: SupabaseClient,
  runId: string | null,
): UseEvidenceStreamResult {
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [partialChairs, setPartialChairs] = useState<Chair[]>([]);
  const [loading, setLoading] = useState(true);
  const channelRef = useRef<RealtimeChannel | null>(null);

  const fetchEvidence = useCallback(async () => {
    if (!runId) return;
    const { data } = await supabase
      .from("evidence_items")
      .select("*, sources(*)")
      .eq("run_id", runId)
      .order("created_at", { ascending: true });
    setEvidence((data as EvidenceItem[] | null) ?? []);
  }, [supabase, runId]);

  const fetchPartialChairs = useCallback(async () => {
    if (!runId) return;
    const { data } = await supabase
      .from("run_events")
      .select("node")
      .eq("run_id", runId)
      .eq("event", "error")
      .like("node", "chair:%");
    const chairs = new Set<Chair>();
    for (const row of (data as { node: string }[] | null) ?? []) {
      const chair = row.node.split(":")[1] as Chair | undefined;
      if (chair) chairs.add(chair);
    }
    setPartialChairs(Array.from(chairs));
  }, [supabase, runId]);

  const refetch = useCallback(async () => {
    await Promise.all([fetchEvidence(), fetchPartialChairs()]);
  }, [fetchEvidence, fetchPartialChairs]);

  useEffect(() => {
    if (!runId) return;

    let cancelled = false;

    setLoading(true);
    refetch().finally(() => {
      if (!cancelled) setLoading(false);
    });

    const channel = supabase
      .channel(`evidence:${runId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "evidence_items", filter: `run_id=eq.${runId}` },
        () => {
          // A specific row could be appended from `payload.new`, but a
          // refetch keeps this path and the reconnect path identical
          // (single source of truth: Postgres), instead of maintaining two
          // slightly different ways of building the same list.
          fetchEvidence();
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "run_events", filter: `run_id=eq.${runId}` },
        () => {
          fetchPartialChairs();
        },
      )
      .subscribe((status: string) => {
        if (status === "SUBSCRIBED") {
          // The reconnect guarantee: every (re)subscribe — including after
          // a dropped socket — re-runs the initial fetch rather than
          // trusting whatever accumulated over the wire.
          refetch();
        }
      });

    channelRef.current = channel;

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
      channelRef.current = null;
    };
  }, [supabase, runId, refetch, fetchEvidence, fetchPartialChairs]);

  return { evidence, partialChairs, loading, refetch };
}

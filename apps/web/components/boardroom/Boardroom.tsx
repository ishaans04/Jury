"use client";

import type { SupabaseClient } from "@supabase/supabase-js";

import { CHAIRS, type Chair, type EvidenceItem } from "@/lib/types";
import { useEvidenceStream } from "@/hooks/useEvidenceStream";
import { ChairColumn } from "./ChairColumn";

interface BoardroomProps {
  supabase: SupabaseClient;
  runId: string;
  /** When the parent already owns the evidence stream (the workspace stage
   * needs per-chair counts too), pass it in so there is one subscription,
   * not two. */
  evidence?: EvidenceItem[];
  partialChairs?: Chair[];
}

/**
 * The live boardroom (F8). Exactly five columns, always, in chair order —
 * PRD §6's fixed chair set — regardless of how much evidence any of them
 * has written so far.
 */
export function Boardroom({ supabase, runId, evidence: external, partialChairs: externalPartial }: BoardroomProps) {
  const stream = useEvidenceStream(supabase, external ? null : runId);
  const evidence = external ?? stream.evidence;
  const partialChairs = externalPartial ?? stream.partialChairs;

  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-5" data-testid="boardroom">
      {CHAIRS.map((chair) => (
        <div key={chair} id={`chair-col-${chair}`} className="min-w-0 scroll-mt-28">
          <ChairColumn
            chair={chair}
            items={evidence.filter((item) => item.chair === chair)}
            partial={partialChairs.includes(chair)}
          />
        </div>
      ))}
    </div>
  );
}

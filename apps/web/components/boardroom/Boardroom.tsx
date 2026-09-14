"use client";

import type { SupabaseClient } from "@supabase/supabase-js";

import { CHAIRS } from "@/lib/types";
import { useEvidenceStream } from "@/hooks/useEvidenceStream";
import { ChairColumn } from "./ChairColumn";

interface BoardroomProps {
  supabase: SupabaseClient;
  runId: string;
}

/**
 * The live boardroom (F8). Exactly five columns, always, in chair order —
 * PRD §6's fixed chair set — regardless of how much evidence any of them
 * has written so far.
 */
export function Boardroom({ supabase, runId }: BoardroomProps) {
  const { evidence, partialChairs } = useEvidenceStream(supabase, runId);

  return (
    <div
      className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-5"
      data-testid="boardroom"
    >
      {CHAIRS.map((chair) => (
        <ChairColumn
          key={chair}
          chair={chair}
          items={evidence.filter((item) => item.chair === chair)}
          partial={partialChairs.includes(chair)}
        />
      ))}
    </div>
  );
}

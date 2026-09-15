"use client";

import { useCrossExamStream } from "@/hooks/useCrossExamStream";

/**
 * Shows transient cross-exam tokens as they stream in (Task 5.6/5.7). This
 * is display-only — nothing here is a source of truth, so a dropped
 * stream renders whatever arrived and stops silently rather than
 * surfacing an error state that would suggest the run itself failed.
 */
export function CrossExamStream({ runId, accessToken }: { runId: string; accessToken?: string }) {
  const { tokens, dropped } = useCrossExamStream(runId, accessToken);

  return (
    <div
      className="rounded-2xl border border-[#EFE7D8] bg-[#F7F1E6] p-3 text-sm text-[#3D3830]"
      data-testid="cross-exam-stream"
    >
      {tokens.length === 0 ? (
        <span className="text-[#9A9183]">Waiting for cross-examination…</span>
      ) : (
        <p>{tokens.join("")}</p>
      )}
      {dropped && tokens.length > 0 && (
        <p className="mt-1 text-xs text-[#9A9183]" data-testid="cross-exam-stream-ended">
          Live stream ended — earlier tokens above are the last received.
        </p>
      )}
    </div>
  );
}

import type { PositionDeltaRecord } from "@/lib/types";
import { CHAIR_LABELS } from "@/lib/types";

/** One position delta: `before -> after` with the reason it moved. */
export function PositionDelta({ delta }: { delta: PositionDeltaRecord }) {
  return (
    <div
      className="flex flex-col gap-1 rounded-2xl border border-[#EFE7D8] bg-white/80 p-3 text-sm"
      data-testid="position-delta"
    >
      <span className="text-xs font-medium uppercase tracking-wide text-[#6B645A]">
        {CHAIR_LABELS[delta.chair]}
      </span>
      <div className="flex flex-wrap items-center gap-2 text-[#3D3830]">
        <span data-testid="position-delta-before">{delta.before}</span>
        <span aria-hidden className="text-[#9A9183]">
          →
        </span>
        <span data-testid="position-delta-after">{delta.after}</span>
      </div>
      <p className="text-xs text-[#6B645A]">{delta.reason}</p>
    </div>
  );
}

import type { SensitivityEntry } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

/**
 * Sensitivity bars ordered by descending absolute elasticity (F11). A
 * plain div-width bar rather than a chart library — no arithmetic happens
 * here beyond sorting and a width percentage, and nothing here recomputes
 * elasticity itself; it only renders what the engine already produced.
 */
export function TornadoChart({ sensitivity }: { sensitivity: SensitivityEntry[] }) {
  if (sensitivity.length === 0) return null;

  const sorted = [...sensitivity].sort((a, b) => Math.abs(b.elasticity) - Math.abs(a.elasticity));
  const maxAbs = Math.max(...sorted.map((s) => Math.abs(s.elasticity)), 1e-9);

  return (
    <div className="flex flex-col gap-2" data-testid="tornado-chart">
      {sorted.map((entry) => {
        const widthPct = (Math.abs(entry.elasticity) / maxAbs) * 100;
        const evidenceBacked = entry.provenance === "evidence_backed";
        return (
          <div
            key={entry.variable}
            className="flex items-center gap-3 text-sm"
            data-testid="tornado-row"
            data-variable={entry.variable}
          >
            <span className="w-32 shrink-0 truncate text-[#3D3830]">{entry.variable}</span>
            <div className="h-3 flex-1 rounded bg-[#EFE6D6]">
              <div
                className={entry.elasticity < 0 ? "h-3 rounded bg-gradient-to-l from-rose-300 to-rose-400" : "h-3 rounded bg-gradient-to-r from-emerald-400 to-emerald-500"}
                style={{ width: `${widthPct}%` }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-xs text-[#6B645A]">
              {entry.elasticity.toFixed(2)}
            </span>
            <Badge variant={evidenceBacked ? "success" : "outline"}>
              {evidenceBacked ? "evidence-backed" : "founder-asserted"}
            </Badge>
            {evidenceBacked && entry.source && (
              <a
                href={entry.source.canonical_url}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate text-xs font-medium text-[#5B5BF7] underline underline-offset-2 hover:text-[#3F3FD0]"
                data-testid="tornado-source-link"
              >
                {entry.source.domain}
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}

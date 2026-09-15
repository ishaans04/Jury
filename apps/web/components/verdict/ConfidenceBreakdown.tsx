import type { ConfidenceComponents } from "@/lib/types";

/**
 * The load-bearing component of Task 5.7 (PRD §9.3): "The UI always
 * displays the four components alongside the total." There is no prop
 * shape here that lets a caller render `total` without `components` — both
 * are required, and the component always renders all four labelled parts
 * plus the literal weighted formula (F12: "displayed with its formula").
 * A bare score with no decomposition is forbidden by construction, not by
 * convention.
 */
export function ConfidenceBreakdown({
  total,
  components,
}: {
  total: number;
  components: ConfidenceComponents;
}) {
  const rows: { label: string; value: number; weight: string }[] = [
    { label: "Coverage", value: components.coverage, weight: "0.30" },
    { label: "Mean strength", value: components.mean_strength, weight: "0.30" },
    { label: "Contradiction", value: components.contradiction, weight: "0.20" },
    { label: "Open critical", value: components.open_critical, weight: "0.20" },
  ];

  return (
    <div
      className="flex flex-col gap-2 rounded-2xl border border-[#EFE7D8] bg-white/80 p-3 text-sm"
      data-testid="confidence-breakdown"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-[#6B645A]">
          Evidence confidence
        </span>
        <span className="text-lg font-semibold text-[#2A2620]" data-testid="confidence-total">
          {total.toFixed(0)}
        </span>
      </div>

      <ul className="flex flex-col gap-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center justify-between text-xs text-[#5A5348]">
            <span>
              {row.label} <span className="text-[#9A9183]">(weight {row.weight})</span>
            </span>
            <span className="font-medium text-[#2A2620]">{row.value.toFixed(2)}</span>
          </li>
        ))}
      </ul>

      <p className="border-t border-[#EFE7D8] pt-2 text-[11px] leading-relaxed text-[#6B645A]" data-testid="confidence-formula">
        0.30·coverage + 0.30·mean_strength + 0.20·(1−contradiction) + 0.20·(1−open_critical)
      </p>
    </div>
  );
}

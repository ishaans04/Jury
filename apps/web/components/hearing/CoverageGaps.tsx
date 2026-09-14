import type { CoverageGap } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

interface CoverageGapsProps {
  gaps: CoverageGap[];
}

const WEIGHT_LABEL: Record<number, string> = {
  1: "blocking",
  0.6: "high",
  0.3: "medium",
};

/**
 * Renders coverage gaps with their questions BEFORE investigation (F6):
 * every hand-seeded assumption class this pitch's assumptions did not
 * touch, ordered highest-stakes first (as `coverage_gaps` already sorts
 * them server-side).
 */
export function CoverageGaps({ gaps }: CoverageGapsProps) {
  if (gaps.length === 0) {
    return (
      <p className="text-sm text-slate-500" data-testid="coverage-gaps-empty">
        No coverage gaps — every checklist class is touched by an assumption.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" data-testid="coverage-gaps">
      {gaps.map((gap) => (
        <li
          key={gap.key}
          className="flex items-start justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2"
          data-testid="coverage-gap"
        >
          <span className="text-sm text-amber-900">{gap.question}</span>
          <Badge variant="warning" className="shrink-0">
            {WEIGHT_LABEL[gap.crit_weight] ?? gap.crit_weight}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

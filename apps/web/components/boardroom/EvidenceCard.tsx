import type { EvidenceItem, SourceRef } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

function firstSource(item: EvidenceItem): SourceRef | null {
  if (!item.sources) return null;
  return Array.isArray(item.sources) ? (item.sources[0] ?? null) : item.sources;
}

const TIER_VARIANT = {
  1: "success",
  2: "secondary",
  3: "outline",
  4: "warning",
} as const;

/**
 * One evidence row rendered as a card. PRD §2.3 / §22: "every number is
 * traceable to a fetchable URL" — this card is where that claim becomes
 * literally true, so the source link and its tier are load-bearing, not
 * decorative: every card renders both, unconditionally.
 */
export function EvidenceCard({ item }: { item: EvidenceItem }) {
  const source = firstSource(item);

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-slate-200 bg-white p-3 text-sm"
      data-testid="evidence-card"
    >
      <div className="flex items-center justify-between gap-2">
        <Badge variant={item.direction === "supports" ? "success" : "destructive"}>
          {item.direction}
        </Badge>
        {source && (
          <Badge variant={TIER_VARIANT[source.tier as 1 | 2 | 3 | 4] ?? "outline"} data-testid="source-tier">
            Tier {source.tier}
          </Badge>
        )}
      </div>

      <p className="text-slate-700">&ldquo;{item.excerpt}&rdquo;</p>

      {item.variable && (
        <p className="text-xs text-slate-500">
          {item.variable}
          {item.value_num !== null ? `: ${item.value_num}${item.unit ? ` ${item.unit}` : ""}` : ""}
        </p>
      )}

      {source ? (
        <a
          href={source.canonical_url}
          target="_blank"
          rel="noopener noreferrer"
          className="truncate text-xs font-medium text-blue-600 underline underline-offset-2 hover:text-blue-800"
          data-testid="source-link"
        >
          {source.domain}
        </a>
      ) : (
        // A row without a joined source should not be able to exist under
        // P1 (evidence is source-backed by a NOT NULL FK), but if the
        // client's join ever comes back empty this must be visibly wrong
        // rather than silently dropping the citation requirement.
        <span className="text-xs font-medium text-red-600" data-testid="source-link-missing">
          source unavailable
        </span>
      )}
    </div>
  );
}

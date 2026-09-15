import { CHAIR_LABELS, type Chair, type EvidenceItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { EvidenceCard } from "./EvidenceCard";

interface ChairColumnProps {
  chair: Chair;
  items: EvidenceItem[];
  partial: boolean;
}

/**
 * One boardroom column. P3: "a chair speaks only when it has a ledger
 * row" — an empty column renders its header and nothing else. No filler
 * card, no "investigating…" shimmer, no text implying activity that
 * hasn't produced a row yet. That would be a lie about the ledger.
 */
export function ChairColumn({ chair, items, partial }: ChairColumnProps) {
  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="chair-column" data-chair={chair}>
      <div className="flex items-center justify-between gap-2 border-b border-[#EFE7D8] pb-2">
        <h3 className="text-sm font-semibold text-[#2A2620]">{CHAIR_LABELS[chair]}</h3>
        <div className="flex items-center gap-2">
          {partial && (
            <Badge variant="warning" data-testid="chair-partial">
              partial
            </Badge>
          )}
          <span className="text-xs text-[#9A9183]">{items.length}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <EvidenceCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

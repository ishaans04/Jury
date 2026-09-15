import type { LedgerVersion } from "@/lib/api";
import { cn } from "@/lib/utils";

interface VersionListProps {
  versions: LedgerVersion[];
  selected: number | null;
  onSelect: (version: number) => void;
}

/** The project's immutable ledger versions, newest first (PRD §7.10). */
export function VersionList({ versions, selected, onSelect }: VersionListProps) {
  if (versions.length === 0) {
    return <p className="text-sm text-[#6B645A]">No ledger versions written yet.</p>;
  }

  const sorted = [...versions].sort((a, b) => b.version - a.version);
  return (
    <ul className="flex flex-col gap-2" data-testid="version-list">
      {sorted.map((v) => {
        const isSelected = v.version === selected;
        return (
          <li key={v.id}>
            <button
              type="button"
              onClick={() => onSelect(v.version)}
              aria-pressed={isSelected}
              data-testid={`version-${v.version}`}
              className={cn(
                "flex w-full items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-left text-sm transition-all",
                isSelected
                  ? "border-[#5B5BF7]/40 bg-white shadow-[0_8px_24px_-12px_rgba(91,91,247,0.45)]"
                  : "border-[#E8DFCF] bg-white/60 hover:bg-white",
              )}
            >
              <span className="font-semibold text-[#2A2620]">v{v.version}</span>
              <span className="text-xs text-[#6B645A]">
                {v.diff.length} change{v.diff.length === 1 ? "" : "s"} ·{" "}
                {new Date(v.created_at).toLocaleDateString()}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

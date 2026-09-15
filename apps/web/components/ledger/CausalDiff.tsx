import type { DiffEntry } from "@/lib/api";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** "The return visit UI shows the diff, not a new report" (PRD §7.10): the
 * backend's one-sentence causal chain, verbatim, above the typed entries it
 * was rendered from. */
export function CausalDiff({ sentence, entries }: { sentence: string; entries: DiffEntry[] }) {
  return (
    <div className="flex flex-col gap-3" data-testid="causal-diff">
      <p
        className="rounded-2xl bg-gradient-to-r from-[#EEF0FF] to-[#F6EEFF] p-4 text-sm font-medium leading-relaxed text-[#2A2620]"
        data-testid="causal-sentence"
      >
        {sentence || "No changes against the previous version."}
      </p>
      {entries.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {entries.map((e, i) => (
            <li
              key={`${e.type}-${e.subject}-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-xl border border-[#EFE7D8] bg-white/70 px-3 py-2 text-xs"
              data-testid="diff-entry"
            >
              <span className="rounded-full bg-[#F3ECDF] px-2 py-0.5 font-medium text-[#6B645A]">{e.type}</span>
              <span className="font-medium text-[#2A2620]">{e.subject}</span>
              <span className="text-[#8C8476] line-through decoration-[#8C8476]/50">{show(e.before)}</span>
              <span aria-hidden className="text-[#B9A788]">→</span>
              <span className="font-semibold text-[#2A2620]">{show(e.after)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

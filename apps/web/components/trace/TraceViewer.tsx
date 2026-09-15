import type { RunEvent } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

function tokenCounts(detail: RunEvent["detail"]): string | null {
  if (!detail) return null;
  const prompt = detail.prompt_tokens;
  const completion = detail.completion_tokens;
  if (typeof prompt !== "number" && typeof completion !== "number") return null;
  return `${prompt ?? 0} in / ${completion ?? 0} out`;
}

function detailMessage(detail: RunEvent["detail"]): string | null {
  if (!detail) return null;
  const message = detail.message;
  return typeof message === "string" ? message : null;
}

/**
 * F17: the run-event log viewer. Every event the run wrote gets a row —
 * node, event kind, latency, token counts — and error rows render
 * unconditionally alongside everything else, so a dropped claim (Phase 2's
 * stage-4 drop) shows up here instead of vanishing into a caught
 * exception.
 */
export function TraceViewer({ events }: { events: RunEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-[#6B645A]">No run events recorded yet.</p>;
  }

  return (
    <div className="flex flex-col gap-1" data-testid="trace-viewer">
      {events.map((event) => {
        const tokens = tokenCounts(event.detail);
        const message = detailMessage(event.detail);
        const isError = event.event === "error";
        return (
          <div
            key={event.id}
            className={
              isError
                ? "flex flex-wrap items-center gap-3 rounded border border-red-200 bg-red-50 p-2 text-xs"
                : "flex flex-wrap items-center gap-3 rounded border border-[#EFE7D8] bg-white/70 p-2 text-xs"
            }
            data-testid={`trace-row-${event.id}`}
            data-event-kind={event.event}
          >
            <span className="text-[#9A9183]">{event.ts}</span>
            <Badge variant="outline">{event.node}</Badge>
            <Badge variant={isError ? "destructive" : "secondary"}>{event.event}</Badge>
            <span className="text-[#5A5348]">
              latency: {event.latency_ms !== null ? `${event.latency_ms}ms` : "—"}
            </span>
            {tokens && <span className="text-[#5A5348]">tokens: {tokens}</span>}
            {message && <span className="text-red-700">{message}</span>}
          </div>
        );
      })}
    </div>
  );
}

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { TraceViewer } from "@/components/trace/TraceViewer";
import type { RunEvent } from "@/lib/api";

function event(overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    id: 1,
    run_id: "run-1",
    ts: new Date().toISOString(),
    node: "chair:market",
    event: "llm_call",
    detail: { prompt_tokens: 120, completion_tokens: 40 },
    latency_ms: 850,
    ...overrides,
  };
}

describe("TraceViewer", () => {
  it("renders every run event with node, event, latency and tokens", () => {
    render(
      <TraceViewer
        events={[
          event({
            id: 1,
            node: "chair:market",
            event: "llm_call",
            latency_ms: 850,
            detail: { prompt_tokens: 120, completion_tokens: 40 },
          }),
        ]}
      />,
    );
    const row = screen.getByTestId("trace-row-1");
    expect(row).toHaveTextContent("chair:market");
    expect(row).toHaveTextContent("llm_call");
    expect(row).toHaveTextContent("850");
    expect(row).toHaveTextContent("120");
    expect(row).toHaveTextContent("40");
  });

  it("renders error rows so a dropped claim is visible", () => {
    render(
      <TraceViewer
        events={[
          event({ id: 2, node: "chair:precedent", event: "error", detail: { message: "stage-4 claim dropped: source unreachable" }, latency_ms: null }),
        ]}
      />,
    );
    const row = screen.getByTestId("trace-row-2");
    expect(row).toHaveTextContent(/error/i);
    expect(row).toHaveTextContent(/stage-4 claim dropped/i);
    expect(row).toHaveAttribute("data-event-kind", "error");
  });

  it("renders nothing hidden — every passed event produces a row", () => {
    const events = [event({ id: 1 }), event({ id: 2 }), event({ id: 3, event: "error" })];
    render(<TraceViewer events={events} />);
    expect(screen.getAllByTestId(/^trace-row-/)).toHaveLength(3);
  });
});

import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { SupabaseClient } from "@supabase/supabase-js";

import { Boardroom } from "@/components/boardroom/Boardroom";
import { ChairColumn } from "@/components/boardroom/ChairColumn";
import { EvidenceCard } from "@/components/boardroom/EvidenceCard";
import type { EvidenceItem } from "@/lib/types";

function evidence(overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    id: overrides.id ?? "e1",
    project_id: "p1",
    run_id: "run-1",
    assumption_id: "a1",
    source_id: "s1",
    chair: overrides.chair ?? "market",
    direction: "supports",
    variable: "cac",
    value_num: 42,
    value_min: null,
    value_max: null,
    unit: "usd",
    scope_geo: "US",
    scope_segment: "smb",
    confidence: 0.7,
    excerpt: "Some pricing page says $42.",
    created_at: new Date().toISOString(),
    sources: { id: "s1", canonical_url: "https://vendor.example.com/pricing", domain: "vendor.example.com", tier: 1 },
    ...overrides,
  };
}

/** A chainable fake query builder mimicking enough of supabase-js's
 * PostgrestFilterBuilder (select/eq/like/order, then thenable) for the
 * hook's exact call shape — see `hooks/useEvidenceStream.ts`. */
function makeChain(getData: () => unknown[]) {
  const chain = {
    select: () => chain,
    eq: () => chain,
    like: () => chain,
    order: () => chain,
    then: (resolve: (v: { data: unknown[] }) => void) => resolve({ data: getData() }),
  };
  return chain;
}

interface FakeSupabase {
  supabase: SupabaseClient;
  emitInsert: (row: EvidenceItem) => void;
  emitReconnect: () => void;
  fromSpy: ReturnType<typeof vi.fn>;
}

function makeFakeSupabase(initialEvidence: EvidenceItem[], errorEvents: { node: string }[] = []): FakeSupabase {
  let rows = initialEvidence;
  let insertCb: (() => void) | null = null;
  let statusCb: ((status: string) => void) | null = null;

  const channel = {
    on: vi.fn((_event: string, config: { table: string }, cb: () => void) => {
      if (config.table === "evidence_items") insertCb = cb;
      return channel;
    }),
    subscribe: vi.fn((cb: (status: string) => void) => {
      statusCb = cb;
      cb("SUBSCRIBED");
      return channel;
    }),
  };

  const fromSpy = vi.fn((table: string) => {
    if (table === "evidence_items") return makeChain(() => rows);
    if (table === "run_events") return makeChain(() => errorEvents);
    return makeChain(() => []);
  });

  const supabase = {
    from: fromSpy,
    channel: vi.fn(() => channel),
    removeChannel: vi.fn(),
  } as unknown as SupabaseClient;

  return {
    supabase,
    fromSpy,
    emitInsert: (row) => {
      rows = [...rows, row];
      insertCb?.();
    },
    emitReconnect: () => {
      statusCb?.("SUBSCRIBED");
    },
  };
}

describe("EvidenceCard", () => {
  it("renders a clickable source link and the source tier", () => {
    render(<EvidenceCard item={evidence()} />);
    const link = screen.getByTestId("source-link");
    expect(link).toHaveAttribute("href", "https://vendor.example.com/pricing");
    expect(link.tagName).toBe("A");
    expect(screen.getByTestId("source-tier")).toHaveTextContent("Tier 1");
  });
});

describe("ChairColumn", () => {
  it("renders nothing in a column with no rows rather than a fake placeholder", () => {
    render(<ChairColumn chair="market" items={[]} partial={false} />);
    expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  });

  it("marks a partial chair visibly", () => {
    render(<ChairColumn chair="customer" items={[]} partial />);
    expect(screen.getByTestId("chair-partial")).toBeInTheDocument();
  });

  it("does not mark a non-partial chair", () => {
    render(<ChairColumn chair="customer" items={[]} partial={false} />);
    expect(screen.queryByTestId("chair-partial")).not.toBeInTheDocument();
  });
});

describe("Boardroom", () => {
  it("renders exactly five columns in chair order", async () => {
    const { supabase } = makeFakeSupabase([]);
    render(<Boardroom supabase={supabase} runId="run-1" />);
    await waitFor(() => expect(screen.getAllByTestId("chair-column")).toHaveLength(5));
    const chairs = screen.getAllByTestId("chair-column").map((el) => el.getAttribute("data-chair"));
    expect(chairs).toEqual(["market", "customer", "precedent", "dependencies", "economics"]);
  });

  it("routes an inserted row to its chair's column", async () => {
    const { supabase, emitInsert } = makeFakeSupabase([evidence({ id: "e1", chair: "market" })]);
    render(<Boardroom supabase={supabase} runId="run-1" />);

    await waitFor(() => expect(screen.getAllByTestId("evidence-card")).toHaveLength(1));

    act(() => {
      emitInsert(evidence({ id: "e2", chair: "customer" }));
    });

    await waitFor(() => expect(screen.getAllByTestId("evidence-card")).toHaveLength(2));
    const customerColumn = document.querySelector('[data-chair="customer"]') as HTMLElement;
    expect(customerColumn.querySelectorAll('[data-testid="evidence-card"]')).toHaveLength(1);
    const marketColumn = document.querySelector('[data-chair="market"]') as HTMLElement;
    expect(marketColumn.querySelectorAll('[data-testid="evidence-card"]')).toHaveLength(1);
  });

  it("marks a chair partial when its run_events carry a chair error row", async () => {
    const { supabase } = makeFakeSupabase([], [{ node: "chair:precedent" }]);
    render(<Boardroom supabase={supabase} runId="run-1" />);
    await waitFor(() => expect(screen.getByTestId("chair-partial")).toBeInTheDocument());
    const precedentColumn = document.querySelector('[data-chair="precedent"]') as HTMLElement;
    expect(precedentColumn.querySelector('[data-testid="chair-partial"]')).toBeTruthy();
  });

  it("refetches on reconnect instead of trusting the socket", async () => {
    const { supabase, fromSpy, emitReconnect } = makeFakeSupabase([evidence({ id: "e1" })]);
    render(<Boardroom supabase={supabase} runId="run-1" />);

    await waitFor(() => expect(screen.getAllByTestId("evidence-card")).toHaveLength(1));
    const callsAfterInitialLoad = fromSpy.mock.calls.filter((c) => c[0] === "evidence_items").length;
    expect(callsAfterInitialLoad).toBeGreaterThanOrEqual(1);

    act(() => {
      emitReconnect();
    });

    await waitFor(() => {
      const callsAfterReconnect = fromSpy.mock.calls.filter((c) => c[0] === "evidence_items").length;
      expect(callsAfterReconnect).toBeGreaterThan(callsAfterInitialLoad);
    });
  });
});

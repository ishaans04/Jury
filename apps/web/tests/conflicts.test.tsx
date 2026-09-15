import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConflictList } from "@/components/conflicts/ConflictList";
import { PositionDelta } from "@/components/conflicts/PositionDelta";
import type { Conflict, PositionDeltaRecord } from "@/lib/types";

function conflict(overrides: Partial<Conflict> = {}): Conflict {
  return {
    id: "c1",
    project_id: "p1",
    run_id: "run-1",
    assumption_id: "a1",
    kind: "chair_vs_chair",
    left_ref: {},
    right_ref: {},
    rule: "R2",
    severity: "high",
    status: "open",
    resolution: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function delta(overrides: Partial<PositionDeltaRecord> = {}): PositionDeltaRecord {
  return {
    id: "d1",
    conflict_id: "c1",
    chair: "market",
    before: "CAC is Rs 200",
    after: "CAC is Rs 350",
    reason: "A tier-1 competitor filing showed higher blended CAC.",
    ...overrides,
  };
}

describe("ConflictList", () => {
  it("labels a founder-vs-world conflict distinctly", () => {
    render(<ConflictList conflicts={[conflict({ kind: "founder_vs_world" })]} />);
    expect(screen.getByText(/founder\s*vs\.?\s*world/i)).toBeInTheDocument();
  });

  it("renders an unresolved conflict as open rather than hiding it", () => {
    render(<ConflictList conflicts={[conflict({ status: "open" })]} />);
    expect(screen.getByTestId("conflict-row")).toBeInTheDocument();
    expect(screen.getByText(/open/i)).toBeInTheDocument();
  });

  it("renders a scope gap as a gap, not as a contradiction", () => {
    render(<ConflictList conflicts={[conflict({ kind: "scope_gap" })]} />);
    expect(screen.getByText(/scope gap/i)).toBeInTheDocument();
    expect(screen.queryByText(/contradiction/i)).not.toBeInTheDocument();
  });

  it("renders each distinct conflict kind with its own label", () => {
    render(
      <ConflictList
        conflicts={[
          conflict({ id: "c1", kind: "chair_vs_chair" }),
          conflict({ id: "c2", kind: "no_evidence" }),
        ]}
      />,
    );
    expect(screen.getByText(/chair\s*vs\.?\s*chair/i)).toBeInTheDocument();
    expect(screen.getByText(/no evidence/i)).toBeInTheDocument();
  });
});

describe("PositionDelta", () => {
  it("renders position deltas as before -> after with a reason", () => {
    render(<PositionDelta delta={delta()} />);
    expect(screen.getByText(/CAC is Rs 200/)).toBeInTheDocument();
    expect(screen.getByText(/CAC is Rs 350/)).toBeInTheDocument();
    expect(screen.getByText(/competitor filing showed higher blended CAC/)).toBeInTheDocument();
  });
});

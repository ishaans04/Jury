import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConfidenceBreakdown } from "@/components/verdict/ConfidenceBreakdown";
import { VerdictCard } from "@/components/verdict/VerdictCard";
import { HungJury } from "@/components/verdict/HungJury";
import type { ConfidenceComponents, Experiment, Verdict } from "@/lib/types";

function components(overrides: Partial<ConfidenceComponents> = {}): ConfidenceComponents {
  return {
    coverage: 0.8,
    mean_strength: 0.6,
    contradiction: 0.1,
    open_critical: 0.0,
    ...overrides,
  };
}

function verdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    id: "v1",
    run_id: "run-1",
    project_id: "p1",
    decision: "PROCEED",
    evidence_confidence: 62,
    components: components(),
    gate_triggered: null,
    friction: [{ kind: "chair_vs_chair", rule: "R2", status: "resolved", resolution: "Market conceded on CAC." }],
    rationale: "Evidence clears the coverage and confidence gates.",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function experiment(overrides: Partial<Experiment> = {}): Experiment {
  return {
    id: "e1",
    assumption_id: "a1",
    target_variable: "retention_90d",
    method: "fake_door",
    instructions: "Run a fake-door landing page for two weeks.",
    kill_criterion: "Kill if signup rate < 2% after 500 visitors.",
    criterion_spec: { metric: "signup_rate", comparator: "<", threshold: 0.02, n: 500 },
    est_cost: 200,
    est_days: 14,
    priority: 1,
    ...overrides,
  };
}

describe("ConfidenceBreakdown", () => {
  it("renders the verdict and all four confidence components together", () => {
    render(<ConfidenceBreakdown total={62} components={components()} />);
    expect(screen.getAllByText(/coverage/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/mean strength/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/contradiction/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/open critical/i).length).toBeGreaterThan(0);
  });

  it("renders the confidence formula with its published weights", () => {
    render(<ConfidenceBreakdown total={62} components={components()} />);
    expect(screen.getAllByText(/0\.30/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/0\.20/).length).toBeGreaterThan(0);
  });

  it("never renders a bare confidence number without its decomposition", () => {
    render(<ConfidenceBreakdown total={62} components={components()} />);
    // The total itself must appear only inside a tree that also carries
    // the decomposition testid — there is no code path in this component
    // that renders the number alone.
    expect(screen.getByTestId("confidence-breakdown")).toHaveTextContent("62");
    expect(screen.getByTestId("confidence-breakdown")).toHaveTextContent(/coverage/i);
  });
});

describe("VerdictCard", () => {
  it("renders the decision", () => {
    render(<VerdictCard verdict={verdict({ decision: "PIVOT" })} />);
    expect(screen.getByText("PIVOT")).toBeInTheDocument();
  });

  it("renders the confidence decomposition inline, never bare", () => {
    render(<VerdictCard verdict={verdict()} />);
    expect(screen.getByTestId("confidence-breakdown")).toBeInTheDocument();
  });

  it("shows the friction summary naming the conflicts that mattered", () => {
    render(
      <VerdictCard
        verdict={verdict({
          friction: [{ kind: "founder_vs_world", rule: "R1", status: "open", resolution: null }],
        })}
      />,
    );
    expect(screen.getByText(/founder\s*vs\.?\s*world/i)).toBeInTheDocument();
  });

  it("renders the gate condition that fired when present", () => {
    render(<VerdictCard verdict={verdict({ decision: "HUNG_JURY", gate_triggered: "coverage_below_0.70" })} />);
    expect(screen.getByText(/coverage_below_0\.70/)).toBeInTheDocument();
  });

  it("does not render a gate condition row when none fired", () => {
    render(<VerdictCard verdict={verdict({ gate_triggered: null })} />);
    expect(screen.queryByTestId("gate-triggered")).not.toBeInTheDocument();
  });
});

describe("HungJury", () => {
  it("renders a hung jury as a refusal with three experiments, not as a failure", () => {
    render(
      <HungJury
        verdict={verdict({ decision: "HUNG_JURY", gate_triggered: "coverage_below_0.70" })}
        experiments={[experiment({ id: "e1" }), experiment({ id: "e2" }), experiment({ id: "e3" })]}
      />,
    );
    expect(screen.getByText(/insufficient evidence to rule/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("experiment-card")).toHaveLength(3);
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });

  it("names the gate condition that fired on a hung jury", () => {
    render(
      <HungJury
        verdict={verdict({ decision: "HUNG_JURY", gate_triggered: "confidence_below_45" })}
        experiments={[experiment({ id: "e1" }), experiment({ id: "e2" }), experiment({ id: "e3" })]}
      />,
    );
    expect(screen.getByText(/confidence_below_45/)).toBeInTheDocument();
  });
});

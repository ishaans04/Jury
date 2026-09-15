import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ExperimentCard } from "@/components/experiments/ExperimentCard";
import type { Experiment } from "@/lib/types";

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

describe("ExperimentCard", () => {
  it("renders the kill criterion on every experiment card", () => {
    render(<ExperimentCard experiment={experiment()} />);
    expect(screen.getByText(/kill if signup rate/i)).toBeInTheDocument();
  });

  it("renders cost and duration on every card", () => {
    render(<ExperimentCard experiment={experiment({ est_cost: 350, est_days: 21 })} />);
    expect(screen.getByText(/350/)).toBeInTheDocument();
    expect(screen.getByText(/21/)).toBeInTheDocument();
  });

  it("renders the retention limitation text when the method is a documented proxy", () => {
    render(
      <ExperimentCard
        experiment={experiment({
          method: "documented_proxy",
          limitation: "90-day retention cannot be observed within a 30-day window; this is a proxy.",
        })}
      />,
    );
    expect(screen.getByText(/cannot be observed within a 30-day window/i)).toBeInTheDocument();
  });

  it("does not render a limitation row for a non-proxy method", () => {
    render(<ExperimentCard experiment={experiment({ method: "fake_door", limitation: null })} />);
    expect(screen.queryByTestId("experiment-limitation")).not.toBeInTheDocument();
  });

  it("never renders a card with a missing kill criterion", () => {
    // The schema makes kill_criterion NOT NULL / min_length 10 (P9); this
    // asserts the UI has no path that swallows it silently even if a row
    // arrived empty.
    render(<ExperimentCard experiment={experiment({ kill_criterion: "" })} />);
    expect(screen.getByTestId("experiment-kill-criterion")).toHaveTextContent(/no kill criterion recorded/i);
  });
});

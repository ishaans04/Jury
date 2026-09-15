import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Breakpoints } from "@/components/economics/Breakpoints";
import { TornadoChart } from "@/components/economics/TornadoChart";
import type { Breakpoint, SensitivityEntry } from "@/lib/types";

function breakpoint(overrides: Partial<Breakpoint> = {}): Breakpoint {
  return {
    variable: "delivery_cost",
    threshold: 70,
    direction: "above",
    unit: "INR",
    output: "contribution_margin",
    sentence: "The business becomes unviable above ₹70 delivery cost.",
    ...overrides,
  };
}

function sensitivityEntry(overrides: Partial<SensitivityEntry> = {}): SensitivityEntry {
  return {
    variable: "cac",
    elasticity: 0.4,
    provenance: "founder_asserted",
    ...overrides,
  };
}

describe("Breakpoints", () => {
  it("renders the breakpoint as a sentence", () => {
    render(<Breakpoints breakpoints={[breakpoint()]} />);
    expect(screen.getByText(/becomes unviable above/i)).toBeInTheDocument();
  });

  it("renders one row per breakpoint verbatim, not a recomputed summary", () => {
    render(
      <Breakpoints
        breakpoints={[
          breakpoint({ variable: "delivery_cost", sentence: "The business becomes unviable above ₹70 delivery cost." }),
          breakpoint({ variable: "cac", sentence: "The business becomes loss-making above ₹500 CAC." }),
        ]}
      />,
    );
    expect(screen.getByText("The business becomes unviable above ₹70 delivery cost.")).toBeInTheDocument();
    expect(screen.getByText("The business becomes loss-making above ₹500 CAC.")).toBeInTheDocument();
  });

  it("renders nothing misleading when there are no breakpoints", () => {
    render(<Breakpoints breakpoints={[]} />);
    expect(screen.queryByTestId("breakpoint-row")).not.toBeInTheDocument();
  });
});

describe("TornadoChart", () => {
  it("renders a tornado chart ordered by descending absolute elasticity", () => {
    render(
      <TornadoChart
        sensitivity={[
          sensitivityEntry({ variable: "small", elasticity: 0.1 }),
          sensitivityEntry({ variable: "big_negative", elasticity: -0.9 }),
          sensitivityEntry({ variable: "medium", elasticity: 0.5 }),
        ]}
      />,
    );
    const rows = screen.getAllByTestId("tornado-row");
    const order = rows.map((r) => r.getAttribute("data-variable"));
    expect(order).toEqual(["big_negative", "medium", "small"]);
  });

  it("marks each parameter as evidence-backed or founder-asserted", () => {
    render(
      <TornadoChart
        sensitivity={[
          sensitivityEntry({ variable: "cac", provenance: "founder_asserted" }),
          sensitivityEntry({
            variable: "retention",
            provenance: "evidence_backed",
            source: { id: "s1", canonical_url: "https://x.example.com", domain: "x.example.com", tier: 1 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/founder.asserted/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence.backed/i)).toBeInTheDocument();
  });

  it("links an evidence-backed parameter to its source", () => {
    render(
      <TornadoChart
        sensitivity={[
          sensitivityEntry({
            variable: "retention",
            provenance: "evidence_backed",
            source: { id: "s1", canonical_url: "https://x.example.com/report", domain: "x.example.com", tier: 1 },
          }),
        ]}
      />,
    );
    const link = screen.getByTestId("tornado-source-link");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "https://x.example.com/report");
  });

  it("does not render a source link for a founder-asserted parameter", () => {
    render(<TornadoChart sensitivity={[sensitivityEntry({ provenance: "founder_asserted" })]} />);
    expect(screen.queryByTestId("tornado-source-link")).not.toBeInTheDocument();
  });
});

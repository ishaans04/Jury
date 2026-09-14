import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { Hearing } from "@/components/hearing/Hearing";
import type { CoverageGap, HearingAssumption } from "@/lib/types";

const confirmHearing = vi.fn().mockResolvedValue({ run_id: "run-1", status: "investigating" });

vi.mock("@/lib/api", () => ({
  api: { confirmHearing: (...args: unknown[]) => confirmHearing(...args) },
}));

const scoredAssumption: HearingAssumption = {
  id: "a1",
  statement: "SMBs will pay $50/month for automated invoice chasing.",
  class_key: "pricing_willingness",
  origin: "founder",
  discovered_by: null,
  criticality: "blocking",
  uncertainty: "uncertain",
  falsifiability: "testable_now",
};

const unscoredAssumption: HearingAssumption = {
  id: "a2",
  statement: "Churn will stay below 5% monthly at scale.",
  class_key: null,
  origin: "discovered",
  discovered_by: "customer",
  criticality: "high",
  uncertainty: "unknown",
  falsifiability: null, // missing the third axis
};

const gaps: CoverageGap[] = [
  { key: "cac_payback", crit_weight: 1, question: "What is the expected CAC payback period?" },
];

function renderHearing(assumptions: HearingAssumption[]) {
  return render(
    <Hearing
      runId="run-1"
      accessToken="token"
      archetype="subscription_saas"
      archetypeConfidence={0.82}
      initialAssumptions={assumptions}
      coverageGaps={gaps}
      onConfirmed={vi.fn()}
    />,
  );
}

function confirmButton() {
  return screen.getByRole("button", { name: /confirm and start investigation/i });
}

describe("Hearing", () => {
  beforeEach(() => {
    confirmHearing.mockClear();
  });

  it("blocks the confirm button until every assumption has all three axes", () => {
    renderHearing([scoredAssumption, unscoredAssumption]);
    expect(confirmButton()).toBeDisabled();
  });

  it("enables confirm once the missing axis is scored", () => {
    renderHearing([scoredAssumption, unscoredAssumption]);
    const falsifiabilitySelects = screen.getAllByLabelText(/falsifiability/i);
    fireEvent.change(falsifiabilitySelects[1], { target: { value: "testable_costly" } });
    expect(confirmButton()).toBeEnabled();
  });

  it("allows editing an assumption statement", () => {
    renderHearing([scoredAssumption]);
    const textarea = screen.getByLabelText(/statement/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Edited statement text, still long enough." } });
    expect(textarea.value).toBe("Edited statement text, still long enough.");
  });

  it("allows deleting an assumption", () => {
    renderHearing([scoredAssumption, unscoredAssumption]);
    expect(screen.getAllByTestId("assumption-row")).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("Delete assumption 1"));
    expect(screen.getAllByTestId("assumption-row")).toHaveLength(1);
  });

  it("allows adding a founder assumption, and the new row starts unscored", () => {
    renderHearing([scoredAssumption]);
    expect(confirmButton()).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /add assumption/i }));
    expect(screen.getAllByTestId("assumption-row")).toHaveLength(2);
    // A freshly added assumption has no scored axes yet, so the gate closes
    // again immediately rather than being trivially satisfiable.
    expect(confirmButton()).toBeDisabled();
  });

  it("renders coverage gaps with their questions before investigation", () => {
    renderHearing([scoredAssumption]);
    expect(screen.getByText(/what is the expected cac payback period\?/i)).toBeInTheDocument();
  });

  it("shows the archetype with its confidence and an override control", () => {
    renderHearing([scoredAssumption]);
    expect(screen.getByTestId("archetype-confidence")).toHaveTextContent("82% confidence");
    const override = screen.getByLabelText(/override archetype/i);
    fireEvent.change(override, { target: { value: "marketplace" } });
    expect(screen.getByTestId("archetype-value")).toHaveTextContent(/marketplace/i);
  });

  it("recovers from a null archetype by requiring an explicit override choice", () => {
    render(
      <Hearing
        runId="run-1"
        accessToken="token"
        archetype={null}
        archetypeConfidence={null}
        initialAssumptions={[scoredAssumption]}
        coverageGaps={[]}
        onConfirmed={vi.fn()}
      />,
    );
    expect(screen.getByTestId("archetype-value")).toHaveTextContent(/not classified/i);
    const override = screen.getByLabelText(/override archetype/i);
    fireEvent.change(override, { target: { value: "d2c" } });
    expect(screen.getByTestId("archetype-value")).toHaveTextContent(/d2c/i);
  });

  it("submits the edited assumptions and calls onConfirmed", async () => {
    const onConfirmed = vi.fn();
    render(
      <Hearing
        runId="run-1"
        accessToken="token"
        archetype="subscription_saas"
        archetypeConfidence={0.82}
        initialAssumptions={[scoredAssumption]}
        coverageGaps={[]}
        onConfirmed={onConfirmed}
      />,
    );
    fireEvent.click(confirmButton());
    await vi.waitFor(() => expect(confirmHearing).toHaveBeenCalledTimes(1));
    expect(confirmHearing).toHaveBeenCalledWith("token", "run-1", expect.any(Array));
    await vi.waitFor(() => expect(onConfirmed).toHaveBeenCalled());
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { VersionList } from "@/components/ledger/VersionList";
import { CausalDiff } from "@/components/ledger/CausalDiff";
import { LogResultForm } from "@/components/ledger/LogResultForm";
import type { LedgerVersion } from "@/lib/api";
import type { Experiment } from "@/lib/types";

function version(n: number): LedgerVersion {
  return {
    id: `v${n}`,
    project_id: "p1",
    version: n,
    run_id: "r1",
    snapshot: {},
    diff: [{ type: "parameter", subject: "price_monthly", before: 499, after: 249 }],
    created_at: new Date().toISOString(),
  };
}

const experiment: Experiment = {
  id: "e1",
  assumption_id: "a1",
  target_variable: "price_monthly",
  method: "presale",
  instructions: "Run a presale.",
  kill_criterion: "Kill if fewer than 10 prepay.",
  criterion_spec: { metric: "prepay_count", comparator: ">=", threshold: 10 },
  est_cost: 50,
  est_days: 7,
  priority: 1,
};

afterEach(() => vi.unstubAllGlobals());

describe("VersionList", () => {
  it("lists versions newest first and reports selection", () => {
    const onSelect = vi.fn();
    render(<VersionList versions={[version(1), version(2)]} selected={2} onSelect={onSelect} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveTextContent("v2");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("version-1"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});

describe("CausalDiff", () => {
  it("renders the causal sentence verbatim above its entries", () => {
    render(
      <CausalDiff
        sentence="Presale result moved price_monthly from 499 to 249."
        entries={version(2).diff}
      />,
    );
    expect(screen.getByTestId("causal-sentence")).toHaveTextContent("Presale result moved price_monthly from 499 to 249.");
    expect(screen.getAllByTestId("diff-entry")).toHaveLength(1);
  });
});

describe("LogResultForm", () => {
  it("posts the measured value and shows the mechanical outcome", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ experiment_status: "passed", assumption_status: "supported", version: 3, diff: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LogResultForm experiment={experiment} accessToken="tok" />);
    fireEvent.change(screen.getByLabelText(/measured prepay_count/i), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /log result/i }));

    await waitFor(() => expect(screen.getByTestId("log-result-outcome")).toHaveTextContent(/passed.*supported.*v3/));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/experiments\/e1\/result$/);
    expect(JSON.parse(init.body)).toEqual({ result_value: 12, result_notes: null });
  });
});

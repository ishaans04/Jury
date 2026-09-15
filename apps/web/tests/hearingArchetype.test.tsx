import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { HearingAssumption } from "@/lib/types";

const calls: string[] = [];
const patchProject = vi.fn(async () => {
  calls.push("patch");
  return {};
});
const confirmHearing = vi.fn(async () => {
  calls.push("confirm");
  return { run_id: "run-1", status: "investigating" };
});

vi.mock("@/lib/api", () => ({
  api: {
    patchProject: (...args: unknown[]) => patchProject(...(args as [])),
    confirmHearing: (...args: unknown[]) => confirmHearing(...(args as [])),
  },
}));

import { Hearing } from "@/components/hearing/Hearing";

const scored: HearingAssumption = {
  statement: "Busy engineers will pay for ready-to-cook dinners.",
  class_key: null,
  origin: "founder",
  discovered_by: null,
  criticality: "blocking",
  uncertainty: "uncertain",
  falsifiability: "testable_now",
};

describe("Hearing archetype override", () => {
  it("saves an overridden archetype to the project before confirming", async () => {
    render(
      <Hearing
        runId="run-1"
        projectId="project-1"
        accessToken="token"
        archetype={null}
        archetypeConfidence={0}
        initialAssumptions={[scored]}
        coverageGaps={[]}
        onConfirmed={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText(/override archetype/i), { target: { value: "d2c" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm and start investigation/i }));

    await vi.waitFor(() => expect(confirmHearing).toHaveBeenCalledTimes(1));
    expect(patchProject).toHaveBeenCalledWith("token", "project-1", { archetype: "d2c" });
    expect(calls).toEqual(["patch", "confirm"]);
  });
});

"use client";

import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Archetype, CoverageGap, HearingAssumption } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ArchetypeBadge } from "./ArchetypeBadge";
import { AssumptionRow } from "./AssumptionRow";
import { CoverageGaps } from "./CoverageGaps";

export interface HearingProps {
  runId: string;
  /** When set, an archetype the founder overrides here is saved to the
   * project before confirming, so the resumed run uses it. */
  projectId?: string;
  accessToken: string;
  archetype: Archetype | null;
  archetypeConfidence: number | null;
  initialAssumptions: HearingAssumption[];
  coverageGaps: CoverageGap[];
  onConfirmed: () => void;
}

function blankAssumption(): HearingAssumption {
  return {
    statement: "",
    class_key: null,
    origin: "founder",
    discovered_by: null,
    // Deliberately null, not defaulted: an added assumption must be scored
    // by the founder like every other row, or the confirm gate (F5) would
    // be trivially satisfiable by clicking "add" and never scoring it.
    criticality: null,
    uncertainty: null,
    falsifiability: null,
  };
}

/**
 * The assumption hearing (F5, PRD §7.3). "Nothing proceeds without
 * confirmation": the confirm button stays disabled until every assumption
 * carries all three axes, and submitting calls
 * `POST /runs/{runId}/hearing/confirm`, which is the only thing that
 * resumes the graph's `interrupt()`.
 */
export function Hearing({
  runId,
  projectId,
  accessToken,
  archetype: initialArchetype,
  archetypeConfidence,
  initialAssumptions,
  coverageGaps,
  onConfirmed,
}: HearingProps) {
  const [archetype, setArchetype] = useState<Archetype | null>(initialArchetype);
  const [assumptions, setAssumptions] = useState<HearingAssumption[]>(initialAssumptions);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allScored = useMemo(
    () =>
      assumptions.length > 0 &&
      assumptions.every(
        (a) =>
          a.statement.trim().length >= 10 &&
          a.criticality !== null &&
          a.uncertainty !== null &&
          a.falsifiability !== null,
      ),
    [assumptions],
  );

  function updateAssumption(index: number, patch: Partial<HearingAssumption>) {
    setAssumptions((prev) => prev.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  }

  function deleteAssumption(index: number) {
    setAssumptions((prev) => prev.filter((_, i) => i !== index));
  }

  function addAssumption() {
    setAssumptions((prev) => [...prev, blankAssumption()]);
  }

  async function confirm() {
    if (!allScored || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (projectId && archetype && archetype !== initialArchetype) {
        await api.patchProject(accessToken, projectId, { archetype });
      }
      await api.confirmHearing(
        accessToken,
        runId,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        assumptions.map(({ id, ...rest }) => rest),
      );
      onConfirmed();
    } catch {
      setError("Could not confirm the hearing. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 py-8">
      <div>
        <h1 className="text-xl font-semibold text-[#2A2620]">Assumption hearing</h1>
        <p className="text-sm text-[#6B645A]">
          Confirm, edit, or add the assumptions The Jury will investigate. Nothing proceeds until every
          assumption is scored on all three axes.
        </p>
      </div>

      <ArchetypeBadge archetype={archetype} confidence={archetypeConfidence} onOverride={setArchetype} />

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-[#2A2620]">Coverage gaps</h2>
        <CoverageGaps gaps={coverageGaps} />
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#2A2620]">Assumptions ({assumptions.length})</h2>
          <Button type="button" variant="outline" size="sm" onClick={addAssumption}>
            Add assumption
          </Button>
        </div>
        {assumptions.map((assumption, index) => (
          <AssumptionRow
            key={assumption.id ?? `new-${index}`}
            index={index}
            assumption={assumption}
            onChange={updateAssumption}
            onDelete={deleteAssumption}
          />
        ))}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-end gap-3 border-t border-[#EFE7D8] pt-4">
        {!allScored && (
          <span className="text-xs text-[#6B645A]">
            Every assumption needs criticality, uncertainty, and falsifiability before you can confirm.
          </span>
        )}
        <Button type="button" disabled={!allScored || submitting} onClick={confirm}>
          {submitting ? "Confirming…" : "Confirm and start investigation"}
        </Button>
      </div>
    </div>
  );
}

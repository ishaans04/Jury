"use client";

import { useState } from "react";

import { api, type LogResultOut } from "@/lib/api";
import type { Experiment } from "@/lib/types";
import { EXPERIMENT_METHOD_LABELS } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface LogResultFormProps {
  experiment: Experiment;
  accessToken: string;
  onLogged?: (result: LogResultOut) => void;
}

/** Return-visit result logging (F14) against `POST /experiments/{id}/result`.
 * The pass/fail call is the backend's mechanical criterion evaluation — this
 * form only submits the founder's measured number and shows what came back. */
export function LogResultForm({ experiment, accessToken, onLogged }: LogResultFormProps) {
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LogResultOut | null>(null);
  const fieldId = `result-${experiment.id ?? experiment.assumption_id}`;
  const { metric, comparator, threshold } = experiment.criterion_spec;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!experiment.id || value.trim() === "" || Number.isNaN(Number(value))) return;
    setSubmitting(true);
    setError(null);
    try {
      const out = await api.logExperimentResult(accessToken, experiment.id, {
        result_value: Number(value),
        result_notes: notes.trim() || null,
      });
      setResult(out);
      onLogged?.(out);
    } catch {
      setError("Could not log this result. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" data-testid="log-result-form">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-[#2A2620]">{EXPERIMENT_METHOD_LABELS[experiment.method]}</span>
        <span className="rounded-full bg-[#F3ECDF] px-2 py-0.5 text-xs text-[#6B645A]">
          {experiment.status ?? "proposed"}
        </span>
      </div>
      <p className="rounded-xl bg-amber-50 p-2 text-xs font-medium text-amber-800">{experiment.kill_criterion}</p>
      <p className="font-mono text-[11px] text-[#8C8476]">
        pass when {metric} {comparator} {threshold}
      </p>
      <div className="flex flex-col gap-1">
        <Label htmlFor={fieldId}>Measured {metric}</Label>
        <Input
          id={fieldId}
          type="number"
          step="any"
          inputMode="decimal"
          required
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${fieldId}-notes`}>Notes (optional)</Label>
        <Textarea id={`${fieldId}-notes`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
      {result && (
        <p className="text-xs text-[#2A2620]" data-testid="log-result-outcome" aria-live="polite">
          Experiment {result.experiment_status} · assumption {result.assumption_status ?? "unchanged"}
          {result.version !== null && ` · ledger v${result.version}`}
        </p>
      )}
      <Button type="submit" size="sm" disabled={submitting || !experiment.id || value.trim() === ""}>
        {submitting ? "Logging…" : "Log result"}
      </Button>
    </form>
  );
}

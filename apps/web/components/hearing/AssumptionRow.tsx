"use client";

import {
  CRITICALITY_OPTIONS,
  FALSIFIABILITY_OPTIONS,
  UNCERTAINTY_OPTIONS,
  type HearingAssumption,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

interface AssumptionRowProps {
  index: number;
  assumption: HearingAssumption;
  onChange: (index: number, patch: Partial<HearingAssumption>) => void;
  onDelete: (index: number) => void;
}

export function AssumptionRow({ index, assumption, onChange, onDelete }: AssumptionRowProps) {
  const fullyScored =
    assumption.criticality !== null &&
    assumption.uncertainty !== null &&
    assumption.falsifiability !== null;

  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
      data-testid="assumption-row"
      data-scored={fullyScored}
    >
      <div className="flex items-start justify-between gap-3">
        <Badge variant={assumption.origin === "founder" ? "outline" : "secondary"}>
          {assumption.origin === "founder" ? "Founder" : `Found by ${assumption.discovered_by}`}
        </Badge>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onDelete(index)}
          aria-label={`Delete assumption ${index + 1}`}
        >
          Delete
        </Button>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor={`statement-${index}`}>Statement</Label>
        <Textarea
          id={`statement-${index}`}
          value={assumption.statement}
          onChange={(e) => onChange(index, { statement: e.target.value })}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`criticality-${index}`}>Criticality</Label>
          <Select
            id={`criticality-${index}`}
            value={assumption.criticality ?? ""}
            onChange={(e) => onChange(index, { criticality: e.target.value as HearingAssumption["criticality"] })}
          >
            <option value="" disabled>
              Score…
            </option>
            {CRITICALITY_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor={`uncertainty-${index}`}>Uncertainty</Label>
          <Select
            id={`uncertainty-${index}`}
            value={assumption.uncertainty ?? ""}
            onChange={(e) => onChange(index, { uncertainty: e.target.value as HearingAssumption["uncertainty"] })}
          >
            <option value="" disabled>
              Score…
            </option>
            {UNCERTAINTY_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor={`falsifiability-${index}`}>Falsifiability</Label>
          <Select
            id={`falsifiability-${index}`}
            value={assumption.falsifiability ?? ""}
            onChange={(e) =>
              onChange(index, { falsifiability: e.target.value as HearingAssumption["falsifiability"] })
            }
          >
            <option value="" disabled>
              Score…
            </option>
            {FALSIFIABILITY_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </Select>
        </div>
      </div>
    </div>
  );
}

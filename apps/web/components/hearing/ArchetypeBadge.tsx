"use client";

import { ARCHETYPE_LABELS, ARCHETYPES, type Archetype } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";

interface ArchetypeBadgeProps {
  archetype: Archetype | null;
  confidence: number | null;
  onOverride: (archetype: Archetype) => void;
}

/**
 * Shows the detected archetype with its confidence and an override
 * control (F4). Handles `archetype === null`, which the detector returns
 * when it cannot classify the pitch — there is no fallback label pretending
 * a classification happened; the founder is asked to pick one explicitly.
 */
export function ArchetypeBadge({ archetype, confidence, onOverride }: ArchetypeBadgeProps) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-[#EFE7D8] bg-[#F7F1E6] p-4">
      <Label>Detected archetype</Label>
      <div className="flex flex-wrap items-center gap-3">
        {archetype ? (
          <Badge variant="secondary" data-testid="archetype-value">
            {ARCHETYPE_LABELS[archetype]}
          </Badge>
        ) : (
          <Badge variant="warning" data-testid="archetype-value">
            Not classified
          </Badge>
        )}
        <span className="text-xs text-[#6B645A]" data-testid="archetype-confidence">
          {confidence !== null ? `${Math.round(confidence * 100)}% confidence` : "no confidence score"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Label htmlFor="archetype-override">Override</Label>
        <Select
          id="archetype-override"
          aria-label="Override archetype"
          value={archetype ?? ""}
          onChange={(e) => onOverride(e.target.value as Archetype)}
          className="max-w-xs"
        >
          <option value="" disabled>
            Choose archetype…
          </option>
          {ARCHETYPES.map((a) => (
            <option key={a} value={a}>
              {ARCHETYPE_LABELS[a]}
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}

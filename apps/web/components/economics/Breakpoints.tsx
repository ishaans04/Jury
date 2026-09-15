import type { Breakpoint } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Renders each breakpoint as its `sentence`, verbatim (PRD §16.5). The
 * engine already produces the sentence ("The business becomes unviable
 * above 70 …") — this component's whole job is to not recompute or
 * paraphrase it, so no arithmetic happens here (F11: "no LLM arithmetic
 * anywhere" extends to the UI too — it never derives its own wording from
 * `threshold`/`direction`/`unit`).
 */
export function Breakpoints({ breakpoints }: { breakpoints: Breakpoint[] }) {
  if (breakpoints.length === 0) return null;

  return (
    <div className="flex flex-col gap-2" data-testid="breakpoints">
      {breakpoints.map((bp) => (
        <Card key={`${bp.variable}-${bp.direction}-${bp.threshold}`} data-testid="breakpoint-row">
          <CardContent className="p-3 text-sm text-[#3D3830]">{bp.sentence}</CardContent>
        </Card>
      ))}
    </div>
  );
}

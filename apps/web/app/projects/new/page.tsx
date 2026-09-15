"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp } from "lucide-react";

import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ChairTable } from "@/components/brand/ChairTable";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { cn } from "@/lib/utils";

const GEO_OPTIONS = ["IN", "US", "EU", "UK", "SEA", "MENA", "LATAM", "GLOBAL"];
const SEGMENT_OPTIONS = ["consumer", "prosumer", "smb", "mid_market", "enterprise", "public_sector"];

/** `/projects/new` — pitch intake, staged as the boardroom: the five chairs
 * wait at the table while the founder writes the pitch in the dock below.
 * Creates the project (archetype detection runs server-side), starts the
 * initial run, and hands off to `/projects/{id}`. */
export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pitch, setPitch] = useState("");
  const [geo, setGeo] = useState("US");
  const [segment, setSegment] = useState("smb");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const length = pitch.trim().length;
  const pitchTooShort = length > 0 && length < 200;
  const pitchTooLong = length > 2000;
  const progress = Math.min(length / 200, 1);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) throw new Error("not authenticated");

      const project = await api.createProject(session.access_token, {
        name,
        pitch,
        target_scope: { geo, segment },
      });
      await api.startRun(session.access_token, project.id, "initial");
      const confidence = project.archetype_confidence;
      const query = confidence !== undefined ? `?ac=${confidence}` : "";
      router.push(`/projects/${project.id}${query}`);
    } catch {
      setError("Could not create the project. Check the pitch length (200-2000 characters) and try again.");
      setSubmitting(false);
    }
  }

  return (
    <WorkspaceShell title="New project">
      <div className="flex flex-1 flex-col justify-between gap-6">
        <div className="flex flex-col items-center gap-2 pt-2 text-center">
          <h1 className="font-display text-4xl tracking-tight text-[#2A2620] sm:text-5xl">
            {submitting ? "The Jury is convening…" : "The Jury is seated."}
          </h1>
          <p className="max-w-md text-sm text-[#6B645A]">
            Describe the idea in 200–2000 characters. The Jury will detect the archetype and draft the
            assumptions you&apos;ll confirm next.
          </p>
        </div>

        <ChairTable thinking={submitting} className="max-w-2xl" />

        <form
          onSubmit={handleSubmit}
          aria-busy={submitting}
          className="glass relative z-40 mx-auto flex w-full max-w-3xl flex-col gap-3 rounded-[2rem] p-3 sm:p-4"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1.4fr_1fr_1fr]">
            <div className="flex flex-col gap-1">
              <Label htmlFor="name">Project name</Label>
              <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="geo">Target geography</Label>
              <Select id="geo" value={geo} onChange={(e) => setGeo(e.target.value)}>
                {GEO_OPTIONS.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="segment">Target segment</Label>
              <Select id="segment" value={segment} onChange={(e) => setSegment(e.target.value)}>
                {SEGMENT_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="relative rounded-3xl border border-[#E2D8C6] bg-white/85 transition-shadow focus-within:border-[#5B5BF7]/50 focus-within:ring-4 focus-within:ring-[#5B5BF7]/15">
            <label htmlFor="pitch" className="sr-only">
              Pitch
            </label>
            <textarea
              id="pitch"
              required
              rows={4}
              minLength={200}
              maxLength={2000}
              value={pitch}
              onChange={(e) => setPitch(e.target.value)}
              placeholder="Pitch your idea: who it's for, what it costs, how it makes money…"
              aria-describedby="pitch-count"
              className="block max-h-[40vh] min-h-28 w-full resize-y rounded-3xl bg-transparent px-5 pb-14 pt-4 text-[15px] leading-relaxed text-[#2A2620] placeholder:text-[#A79E8F] focus:outline-none"
            />
            <div className="absolute inset-x-3 bottom-3 flex items-center justify-between gap-3">
              <span id="pitch-count" className="flex items-center gap-2 text-xs text-[#6B645A]" aria-live="polite">
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-[#EFE6D6]" aria-hidden>
                  <span
                    className={cn(
                      "block h-full rounded-full transition-all duration-300",
                      pitchTooLong ? "bg-rose-500" : progress >= 1 ? "bg-emerald-500" : "bg-[#5B5BF7]",
                    )}
                    style={{ width: `${progress * 100}%` }}
                  />
                </span>
                {length} / 2000
                {pitchTooShort && " — needs at least 200 characters"}
                {pitchTooLong && " — over the 2000 character limit"}
              </span>
              <Button
                type="submit"
                aria-label="Create project and start hearing"
                disabled={submitting || pitchTooShort || pitchTooLong || length === 0}
              >
                <span className="hidden sm:inline">{submitting ? "Creating…" : "Stress Test"}</span>
                <ArrowUp className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>

          {error && (
            <p className="px-2 text-sm text-red-700" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </WorkspaceShell>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";

const GEO_OPTIONS = ["IN", "US", "EU", "UK", "SEA", "MENA", "LATAM", "GLOBAL"];
const SEGMENT_OPTIONS = ["consumer", "prosumer", "smb", "mid_market", "enterprise", "public_sector"];

/** `/projects/new` — pitch intake. Creates the project (which triggers
 * archetype detection server-side), starts the initial run, and hands off
 * to `/projects/{id}`, which renders the hearing once the run reaches it. */
export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pitch, setPitch] = useState("");
  const [geo, setGeo] = useState("US");
  const [segment, setSegment] = useState("smb");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pitchTooShort = pitch.trim().length > 0 && pitch.trim().length < 200;
  const pitchTooLong = pitch.trim().length > 2000;

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
    <div className="mx-auto flex max-w-2xl flex-col gap-6 py-12">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">New project</h1>
        <p className="text-sm text-slate-500">
          Describe the idea in 200–2000 characters. Jury will detect the archetype and draft the
          assumptions you&apos;ll confirm next.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="name">Project name</Label>
          <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="pitch">Pitch</Label>
          <Textarea
            id="pitch"
            required
            rows={8}
            minLength={200}
            maxLength={2000}
            value={pitch}
            onChange={(e) => setPitch(e.target.value)}
          />
          <span className="text-xs text-slate-400">
            {pitch.trim().length} / 2000
            {pitchTooShort && " — needs at least 200 characters"}
            {pitchTooLong && " — over the 2000 character limit"}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-4">
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

        {error && <p className="text-sm text-red-600">{error}</p>}

        <Button
          type="submit"
          disabled={submitting || pitchTooShort || pitchTooLong || pitch.trim().length === 0}
        >
          {submitting ? "Creating…" : "Create project and start hearing"}
        </Button>
      </form>
    </div>
  );
}

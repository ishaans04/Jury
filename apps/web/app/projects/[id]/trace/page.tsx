import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { api, type RunEvent, type RunOut } from "@/lib/api";
import { TraceViewer } from "@/components/trace/TraceViewer";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { cn } from "@/lib/utils";

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ run?: string }>;
}

export const metadata = { title: "Trace" };

/** `/projects/{id}/trace` — F17's run-event log, read through
 * `GET /runs/{id}/events` for the selected run (latest by default). */
export default async function TracePage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { run: requestedRun } = await searchParams;
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect("/?session=unavailable");
  }

  const project = await api.getProject(session.access_token, id).catch(() => null);
  if (!project) notFound();

  const { data: runRows } = await supabase
    .from("runs")
    .select("*")
    .eq("project_id", id)
    .order("started_at", { ascending: false });
  const runs = (runRows as RunOut[] | null) ?? [];
  const selected = runs.find((r) => r.id === requestedRun) ?? runs[0] ?? null;

  const events: RunEvent[] = selected
    ? await api.getRunEvents(session.access_token, selected.id).catch(() => [])
    : [];
  const errorCount = events.filter((e) => e.event === "error").length;

  return (
    <WorkspaceShell
      title={project.name}
      actions={
        <Link href={`/projects/${id}`} className="rounded-full px-3 py-2 text-sm text-[#5A5348] hover:bg-white/70">
          Boardroom
        </Link>
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#5B5BF7]">Trace</p>
            <h1 className="font-display text-4xl tracking-tight text-[#2A2620] sm:text-5xl">Run events</h1>
          </div>
          {selected && (
            <p className="text-sm text-[#6B645A]">
              {events.length} events · {errorCount} error{errorCount === 1 ? "" : "s"} · {selected.status}
            </p>
          )}
        </div>

        {runs.length > 1 && (
          <nav aria-label="Runs" className="flex flex-wrap gap-2">
            {runs.map((r) => (
              <Link
                key={r.id}
                href={`/projects/${id}/trace?run=${r.id}`}
                aria-current={r.id === selected?.id ? "page" : undefined}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs transition-colors",
                  r.id === selected?.id ? "bg-[#2A2620] text-white" : "glass-chip text-[#5A5348] hover:bg-white",
                )}
              >
                {r.kind} · {new Date(r.started_at).toLocaleString()}
              </Link>
            ))}
          </nav>
        )}

        <div className="glass rounded-[2rem] p-3 sm:p-5">
          {selected ? (
            <TraceViewer events={events} />
          ) : (
            <p className="p-6 text-sm text-[#6B645A]">No run has been started for this project yet.</p>
          )}
        </div>
      </div>
    </WorkspaceShell>
  );
}

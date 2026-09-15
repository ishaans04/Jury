import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { api, type RunOut } from "@/lib/api";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { ProjectView } from "./ProjectView";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** `/projects/{id}` — restores the full ledger state, any open run
 * (PRD §14.2). The latest run is read directly from `runs` via
 * `supabase-js` (RLS-protected, `own runs` policy) since FastAPI has no
 * "latest run for a project" route — only `GET /runs/{id}` for a run
 * already known by id. */
export default async function ProjectPage({ params }: PageProps) {
  const { id } = await params;
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
    .order("started_at", { ascending: false })
    .limit(1);

  const latestRun = (runRows?.[0] as RunOut | undefined) ?? null;

  return (
    <WorkspaceShell
      title={project.name}
      actions={
        <Link href={`/projects/${id}/trace`} className="rounded-full px-3 py-2 text-sm text-[#5A5348] hover:bg-white/70">
          Trace
        </Link>
      }
    >
      <h1 className="sr-only">{project.name}</h1>
      <ProjectView project={project} initialRun={latestRun} accessToken={session.access_token} />
    </WorkspaceShell>
  );
}

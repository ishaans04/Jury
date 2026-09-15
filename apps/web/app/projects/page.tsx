import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowUpRight, Plus } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { api } from "@/lib/api";
import { ARCHETYPE_LABELS, type Archetype } from "@/lib/types";
import { buttonVariants } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { MiniBot } from "@/components/brand/MiniBot";
import { CHAIR_FLOW as TABLE_ORDER } from "@/lib/chairs";

export const metadata = { title: "Your projects" };

/** `/projects` — the dashboard. One of the four screens in the whole auth
 * and navigation surface (PRD §14.2). */
export default async function ProjectsPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect("/?session=unavailable");
  }

  const projects = await api.listProjects(session.access_token).catch(() => []);

  return (
    <WorkspaceShell>
      <div className="flex flex-col gap-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#5B5BF7]">The Jury</p>
            <h1 className="font-display text-5xl tracking-tight text-[#2A2620]">Your projects</h1>
          </div>
          <Link href="/projects/new" className={buttonVariants()}>
            <Plus className="h-4 w-4" aria-hidden />
            New project
          </Link>
        </div>

        {projects.length === 0 ? (
          <div className="glass flex flex-col items-center gap-6 rounded-[2rem] px-6 py-14 text-center">
            <div className="flex w-full max-w-sm items-end justify-center gap-1">
              {TABLE_ORDER.map((c, i) => (
                <div key={c} className="w-14">
                  <MiniBot seat={c} delay={i * 0.2} />
                </div>
              ))}
            </div>
            <p className="max-w-md text-[#5A5348]">
              No projects yet. Start one from a pitch to see the assumption hearing.
            </p>
            <Link href="/projects/new" className={buttonVariants({ size: "lg" })}>
              Stress Test Your Idea
            </Link>
          </div>
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <li key={project.id}>
                <Link
                  href={`/projects/${project.id}`}
                  className="group shadow-soft flex h-full flex-col justify-between gap-6 rounded-3xl border border-white/80 bg-[#FFFDF8]/90 p-5 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_24px_50px_-24px_rgba(91,91,247,0.45)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#5B5BF7]/25"
                >
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="text-lg font-semibold tracking-tight text-[#2A2620]">{project.name}</h2>
                    <ArrowUpRight
                      className="h-5 w-5 shrink-0 text-[#9A9183] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-[#5B5BF7]"
                      aria-hidden
                    />
                  </div>
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="rounded-full bg-[#EEF0FF] px-2.5 py-1 font-medium text-[#4B4BD6]">
                      {project.archetype
                        ? ARCHETYPE_LABELS[project.archetype as Archetype]
                        : "Archetype not yet detected"}
                    </span>
                    <span className="text-[#9A9183]">Created {new Date(project.created_at).toLocaleDateString()}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </WorkspaceShell>
  );
}

import Link from "next/link";
import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { api } from "@/lib/api";
import { ARCHETYPE_LABELS, type Archetype } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** `/projects` — the dashboard. One of the four screens in the whole auth
 * and navigation surface (PRD §14.2). */
export default async function ProjectsPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect("/login?next=%2Fprojects");
  }

  const projects = await api.listProjects(session.access_token).catch(() => []);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Your projects</h1>
        <Link
          href="/projects/new"
          className={cn(
            "inline-flex h-10 items-center justify-center rounded-md bg-slate-900 px-4 text-sm font-medium text-white hover:bg-slate-800",
          )}
        >
          New project
        </Link>
      </div>

      {projects.length === 0 ? (
        <p className="text-sm text-slate-500">
          No projects yet. Start one from a pitch to see the assumption hearing.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {projects.map((project) => (
            <Link key={project.id} href={`/projects/${project.id}`}>
              <Card className="transition-shadow hover:shadow-md">
                <CardHeader>
                  <CardTitle>{project.name}</CardTitle>
                  <CardDescription>
                    {project.archetype
                      ? ARCHETYPE_LABELS[project.archetype as Archetype]
                      : "Archetype not yet detected"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="text-xs text-slate-400">
                  Created {new Date(project.created_at).toLocaleDateString()}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

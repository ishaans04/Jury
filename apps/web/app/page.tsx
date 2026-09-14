import { redirect } from "next/navigation";

/** The root route has no product surface of its own — the four-screen auth
 * and navigation surface (PRD §14.2) starts at `/projects` for a signed-in
 * founder, or `/login` otherwise (`middleware.ts` handles that redirect). */
export default function RootPage() {
  redirect("/projects");
}

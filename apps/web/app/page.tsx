import { Landing } from "@/components/landing/Landing";

/** `/` — the public landing page for The Jury. Signed-in surfaces start at
 * `/projects`, which `middleware.ts` gates behind sign-in. */
export default function RootPage() {
  return <Landing />;
}

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

/**
 * Server-side Supabase client for Server Components, Route Handlers and
 * `middleware.ts`. Cookie-based session (PRD §14.3): reads/writes the
 * session cookies so the SSR session refresh keeps the ~30-day session
 * alive across requests without any client-side token juggling.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        } catch {
          // Called from a Server Component that cannot set cookies; the
          // middleware's own setAll (below) is what actually persists the
          // refreshed session, so this is safe to ignore here.
        }
      },
    },
  });
}

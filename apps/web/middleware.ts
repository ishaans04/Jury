import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "@/lib/supabase/env";

/**
 * Refreshes the Supabase session on every request. There is no sign-in
 * screen: the first visit to any `/projects*` route silently creates an
 * anonymous Supabase session, whose JWT (`aud: authenticated`) is exactly
 * what FastAPI and RLS already key on. Requires anonymous sign-ins to be
 * enabled on the Supabase project.
 */
export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user && request.nextUrl.pathname.startsWith("/projects")) {
    const { error } = await supabase.auth.signInAnonymously();
    if (error) {
      const home = new URL("/", request.url);
      home.searchParams.set("session", "unavailable");
      return NextResponse.redirect(home);
    }
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all paths except static assets, so the session refresh runs on
     * every navigable route while leaving Next's own internals alone.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};

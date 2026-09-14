import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

/**
 * `/auth/callback` — PRD §14.2: `exchangeCodeForSession()`, upsert into
 * `profiles`, redirect to `/projects` (or the original `next` target the
 * login page attached to the magic link, e.g. the deep link a
 * `middleware.ts` redirect produced).
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") || "/projects";

  if (code) {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);

    if (!error && data.user) {
      await supabase
        .from("profiles")
        .upsert({ id: data.user.id, email: data.user.email ?? "" }, { onConflict: "id" });

      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_callback_failed`);
}

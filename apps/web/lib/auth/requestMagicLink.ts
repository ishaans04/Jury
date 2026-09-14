import type { SupabaseClient } from "@supabase/supabase-js";

export type MagicLinkResult =
  | { ok: true }
  | { ok: false; reason: "rate_limited" | "error"; message: string };

/**
 * The one and only way this product sends a sign-in link (F1): checks the
 * per-email Upstash bucket (via the `/api/auth/request-link` route, which
 * is where that check is actually enforced — see its handler) and, only if
 * that passes, calls `supabase.auth.signInWithOtp`. `signInWithPassword`
 * is never imported or called anywhere in this module or its callers.
 */
export async function requestMagicLink(
  supabase: SupabaseClient,
  email: string,
  redirectTo: string,
): Promise<MagicLinkResult> {
  const rateLimitRes = await fetch("/api/auth/request-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });

  if (rateLimitRes.status === 429) {
    return {
      ok: false,
      reason: "rate_limited",
      message: "Too many magic link requests for this email. Try again in a bit.",
    };
  }
  if (!rateLimitRes.ok) {
    return { ok: false, reason: "error", message: "Something went wrong. Please try again." };
  }

  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: redirectTo },
  });

  if (error) {
    return { ok: false, reason: "error", message: error.message };
  }
  return { ok: true };
}

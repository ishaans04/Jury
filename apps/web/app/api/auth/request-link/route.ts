import { NextResponse } from "next/server";

import { checkMagicLinkRateLimit } from "@/lib/rateLimit";

/**
 * PRD §14.3 / §18: "a second Upstash token bucket caps requests per email
 * per hour to protect the free email quota." This route is that second
 * gate. It does not itself send the magic link — the client still calls
 * `supabase.auth.signInWithOtp` (see `lib/auth/requestMagicLink.ts`), which
 * carries Supabase's own rate limiting — this route only decides whether
 * that call is allowed to happen at all.
 */
export async function POST(request: Request) {
  let email: unknown;
  try {
    const body = await request.json();
    email = body?.email;
  } catch {
    return NextResponse.json({ error: "invalid body" }, { status: 400 });
  }

  if (typeof email !== "string" || !email.includes("@")) {
    return NextResponse.json({ error: "invalid email" }, { status: 400 });
  }

  const { allowed } = await checkMagicLinkRateLimit(email);
  if (!allowed) {
    return NextResponse.json(
      { error: "rate_limited", message: "Too many requests for this email." },
      { status: 429 },
    );
  }

  return NextResponse.json({ ok: true });
}

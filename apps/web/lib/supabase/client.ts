"use client";

import { createBrowserClient } from "@supabase/ssr";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

/**
 * Browser Supabase client. Used for: `signInWithOtp` on the login page, and
 * direct `supabase-js` reads under RLS (assumptions, evidence, conflicts,
 * verdicts, run_events, versions) — PRD §13: "Reads the client can satisfy
 * directly through supabase-js with RLS ... should go direct, not through
 * FastAPI." Never used to call `signInWithPassword` — no such call exists
 * anywhere in this codebase (F1).
 */
export function createClient() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}

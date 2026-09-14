/**
 * Centralised, lazy read of the Supabase public env vars.
 *
 * `.env.example` documents `NEXT_PUBLIC_SUPABASE_URL` /
 * `NEXT_PUBLIC_SUPABASE_ANON_KEY` as empty by default (they are filled in
 * per-deploy, never committed). The app's unit/component test suite must
 * run without them (task brief, "Existing state"), so this module falls
 * back to harmless placeholder values instead of throwing at import time --
 * every test that cares about Supabase behaviour mocks
 * `@/lib/supabase/client` or `@/lib/supabase/server` directly rather than
 * relying on a real project.
 */
export const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL || "http://localhost:54321";
export const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "test-anon-key";

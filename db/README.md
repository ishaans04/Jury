# Database

**Migrations live in [`supabase/migrations/`](../supabase/migrations/), not here.**

The Supabase CLI hardcodes that path for `supabase db reset` and offers no way to
redirect it, so keeping a second copy under `db/migrations/` would mean two
sources of truth for the schema. This deviates from the repository layout in
`docs/PRD.md` §21.4, which lists `db/migrations/`.

Seeds are unaffected and remain canonical here in [`seed/`](seed/) —
`supabase/config.toml` accepts a relative path to them.

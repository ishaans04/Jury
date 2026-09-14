/**
 * Per-email magic-link rate limiter (PRD §14.3 / §18): "a second Upstash
 * token bucket caps requests per email per hour to protect the free email
 * quota." This is deliberately a SECOND gate in front of
 * `supabase.auth.signInWithOtp` — Supabase has its own limiter, but that one
 * is not ours to configure or test, so this module is what the product
 * actually controls and what the test suite can assert against.
 *
 * Backed by Upstash when `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`
 * are set (production). Falls back to an in-memory fixed-window counter
 * otherwise, so `npm test` and local dev work with no external service —
 * the brief requires the suite run "without them" (no live Supabase/Upstash
 * env). The in-memory fallback is per-process and NOT suitable for a
 * multi-instance deployment; that trade-off is intentional for local/dev
 * and is why production must set the Upstash env vars.
 */

const WINDOW_MS = 60 * 60 * 1000; // 1 hour
const MAX_REQUESTS_PER_WINDOW = 3;

interface Bucket {
  count: number;
  windowStart: number;
}

const memoryBuckets = new Map<string, Bucket>();

function checkInMemory(key: string, now: number): { allowed: boolean; remaining: number } {
  const bucket = memoryBuckets.get(key);
  if (!bucket || now - bucket.windowStart >= WINDOW_MS) {
    memoryBuckets.set(key, { count: 1, windowStart: now });
    return { allowed: true, remaining: MAX_REQUESTS_PER_WINDOW - 1 };
  }
  if (bucket.count >= MAX_REQUESTS_PER_WINDOW) {
    return { allowed: false, remaining: 0 };
  }
  bucket.count += 1;
  return { allowed: true, remaining: MAX_REQUESTS_PER_WINDOW - bucket.count };
}

/** Test-only: clears the in-memory fallback bucket state between tests. */
export function _resetMemoryBucketsForTests() {
  memoryBuckets.clear();
}

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

let upstashRatelimit: {
  limit: (key: string) => Promise<{ success: boolean; remaining: number }>;
} | null | undefined;

async function getUpstashLimiter() {
  if (upstashRatelimit !== undefined) return upstashRatelimit;

  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) {
    upstashRatelimit = null;
    return upstashRatelimit;
  }

  const { Ratelimit } = await import("@upstash/ratelimit");
  const { Redis } = await import("@upstash/redis");
  const redis = new Redis({ url, token });
  const limiter = new Ratelimit({
    redis,
    limiter: Ratelimit.fixedWindow(MAX_REQUESTS_PER_WINDOW, "1 h"),
    prefix: "jury:magic-link",
  });
  upstashRatelimit = {
    limit: async (key: string) => {
      const result = await limiter.limit(key);
      return { success: result.success, remaining: result.remaining };
    },
  };
  return upstashRatelimit;
}

export interface RateLimitResult {
  allowed: boolean;
  remaining: number;
}

/**
 * Checks and consumes one request from the per-email hourly bucket.
 * Returns `allowed: false` once the bucket for that email is exhausted for
 * the current window.
 */
export async function checkMagicLinkRateLimit(email: string): Promise<RateLimitResult> {
  const key = normalizeEmail(email);
  const limiter = await getUpstashLimiter();
  if (limiter) {
    const { success, remaining } = await limiter.limit(key);
    return { allowed: success, remaining };
  }
  return checkInMemory(key, Date.now());
}

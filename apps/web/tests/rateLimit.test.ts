import { beforeEach, describe, expect, it } from "vitest";

import { _resetMemoryBucketsForTests, checkMagicLinkRateLimit } from "@/lib/rateLimit";

describe("checkMagicLinkRateLimit", () => {
  beforeEach(() => {
    _resetMemoryBucketsForTests();
    delete process.env.UPSTASH_REDIS_REST_URL;
    delete process.env.UPSTASH_REDIS_REST_TOKEN;
  });

  it("allows requests under the per-email cap", async () => {
    const a = await checkMagicLinkRateLimit("founder@example.com");
    const b = await checkMagicLinkRateLimit("founder@example.com");
    expect(a.allowed).toBe(true);
    expect(b.allowed).toBe(true);
  });

  it("blocks a repeated request once the same email exhausts its bucket", async () => {
    const email = "founder@example.com";
    const results = [];
    for (let i = 0; i < 5; i += 1) {
      results.push(await checkMagicLinkRateLimit(email));
    }
    expect(results.some((r) => r.allowed === false)).toBe(true);
  });

  it("tracks buckets independently per email", async () => {
    const email = "capped@example.com";
    for (let i = 0; i < 5; i += 1) {
      await checkMagicLinkRateLimit(email);
    }
    const other = await checkMagicLinkRateLimit("someone-else@example.com");
    expect(other.allowed).toBe(true);
  });

  it("normalizes email case and whitespace to the same bucket", async () => {
    for (let i = 0; i < 5; i += 1) {
      await checkMagicLinkRateLimit(" Founder@Example.com ");
    }
    const blocked = await checkMagicLinkRateLimit("founder@example.com");
    expect(blocked.allowed).toBe(false);
  });
});

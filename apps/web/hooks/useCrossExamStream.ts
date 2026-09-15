"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

interface UseCrossExamStreamResult {
  tokens: string[];
  connected: boolean;
  dropped: boolean;
}

/**
 * Consumes `GET /runs/{id}/cross-exam/stream` (PRD §10.2, Task 5.6's
 * `apps/api/jury/api/routers/stream.py`) — the *only* SSE route in the
 * app, and it carries transient cross-exam prose tokens, nothing durable.
 * Durable state (a chair "speaking") is a persisted row reached through
 * Supabase Realtime elsewhere (`useEvidenceStream`); this hook's tokens
 * are never written back anywhere, so losing the connection can only ever
 * lose *display*, never state — this must never throw out of the
 * component tree on a drop, it just stops appending and flips `dropped`.
 *
 * Uses `fetch` + a manual reader rather than `EventSource`, because
 * `EventSource` cannot attach an `Authorization` header and the route
 * requires auth.
 */
export function useCrossExamStream(runId: string | null, accessToken: string | undefined): UseCrossExamStreamResult {
  const [tokens, setTokens] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [dropped, setDropped] = useState(false);
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (!runId) return;
    cancelledRef.current = false;
    setTokens([]);
    setDropped(false);

    async function run() {
      try {
        const res = await fetch(`${API_BASE_URL}/runs/${runId}/cross-exam/stream`, {
          headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
        });
        if (!res.ok || !res.body) {
          setDropped(true);
          return;
        }
        setConnected(true);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!cancelledRef.current) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("data:")) {
              const token = line.slice(5).trimStart();
              if (token.length > 0 && !cancelledRef.current) {
                setTokens((prev) => [...prev, token]);
              }
            }
            // Comment lines (`: heartbeat`, `: stream-open`) and blank
            // event separators are intentionally ignored — they carry no
            // token payload.
          }
        }
      } catch {
        // A dropped socket (network error, server closing the stream when
        // the run leaves cross_exam) is expected, not exceptional — PRD
        // §10.2's own argument for not depending on this channel for
        // state. Swallow it and let the page keep whatever tokens already
        // rendered.
      } finally {
        if (!cancelledRef.current) {
          setConnected(false);
          setDropped(true);
        }
      }
    }

    run();

    return () => {
      cancelledRef.current = true;
    };
  }, [runId, accessToken]);

  return { tokens, connected, dropped };
}

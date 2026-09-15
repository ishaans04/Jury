import { describe, expect, it, vi, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

import { CrossExamStream } from "@/components/hearing/CrossExamStream";

function sseResponse(chunks: string[], opts: { ok?: boolean; throwAfter?: boolean } = {}) {
  let i = 0;
  const body = {
    getReader() {
      return {
        async read() {
          if (i < chunks.length) {
            const chunk = chunks[i++];
            return { done: false, value: new TextEncoder().encode(chunk) };
          }
          if (opts.throwAfter) {
            throw new Error("stream dropped");
          }
          return { done: true, value: undefined };
        },
        releaseLock() {},
      };
    },
  };
  return {
    ok: opts.ok ?? true,
    status: opts.ok === false ? 500 : 200,
    body,
  };
}

describe("CrossExamStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders transient tokens as they arrive over the stream", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(["data: Founder\n\n", "data:  claims retention is 40%\n\n"]),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<CrossExamStream runId="run-1" accessToken="tok" />);

    await waitFor(() => expect(screen.getByTestId("cross-exam-stream")).toHaveTextContent("Founder"));
    await waitFor(() =>
      expect(screen.getByTestId("cross-exam-stream")).toHaveTextContent("claims retention is 40%"),
    );
  });

  it("does not break the page when the stream drops", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["data: partial token\n\n"], { throwAfter: true }));
    vi.stubGlobal("fetch", fetchMock);

    render(<CrossExamStream runId="run-1" accessToken="tok" />);

    await waitFor(() => expect(screen.getByTestId("cross-exam-stream")).toHaveTextContent("partial token"));
    // The drop should not throw out of the component tree — the page around
    // it stays mounted and rendered.
    expect(screen.getByTestId("cross-exam-stream")).toBeInTheDocument();
  });

  it("does not break the page when the fetch itself rejects", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network error"));
    vi.stubGlobal("fetch", fetchMock);

    render(<CrossExamStream runId="run-1" accessToken="tok" />);

    await waitFor(() => expect(screen.getByTestId("cross-exam-stream")).toBeInTheDocument());
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import LoginPage from "@/app/login/page";

const signInWithOtp = vi.fn().mockResolvedValue({ error: null });
const signInWithPassword = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signInWithOtp, signInWithPassword } }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

function fillEmailAndSubmit(email = "founder@example.com") {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: /send magic link/i }));
}

describe("LoginPage", () => {
  beforeEach(() => {
    signInWithOtp.mockClear().mockResolvedValue({ error: null });
    signInWithPassword.mockClear();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }) as unknown as typeof fetch;
  });

  it("renders no password input anywhere in the login tree", () => {
    const { container } = render(<LoginPage />);
    expect(container.querySelector('input[type="password"]')).toBeNull();
  });

  it("calls signInWithOtp and never signInWithPassword", async () => {
    render(<LoginPage />);
    fillEmailAndSubmit();

    await waitFor(() => expect(signInWithOtp).toHaveBeenCalledTimes(1));
    expect(signInWithOtp).toHaveBeenCalledWith(
      expect.objectContaining({ email: "founder@example.com" }),
    );
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("shows a check-your-inbox state after submit", async () => {
    render(<LoginPage />);
    fillEmailAndSubmit();

    expect(await screen.findByTestId("check-inbox")).toBeInTheDocument();
  });

  it("rate-limits repeated magic-link requests for the same email", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ error: "rate_limited" }),
    }) as unknown as typeof fetch;

    render(<LoginPage />);
    fillEmailAndSubmit();

    expect(await screen.findByTestId("login-error")).toBeInTheDocument();
    // The second Upstash-backed bucket blocked the request before Supabase
    // was ever asked to send an email — that's the point of the second gate.
    expect(signInWithOtp).not.toHaveBeenCalled();
  });
});

"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { requestMagicLink } from "@/lib/auth/requestMagicLink";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * `/login` — F1: email in, magic link out. There is no password field
 * anywhere on this page, nor anywhere else in the product (PRD §14.1/14.5).
 */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email) return;
    setStatus("sending");
    setMessage(null);

    const supabase = createClient();
    const next = searchParams.get("next") || "/projects";
    const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;

    const result = await requestMagicLink(supabase, email, redirectTo);
    if (result.ok) {
      setStatus("sent");
    } else {
      setStatus("error");
      setMessage(result.message);
    }
  }

  if (status === "sent") {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-3 py-24 text-center">
        <h1 className="text-lg font-semibold text-slate-900">Check your inbox</h1>
        <p className="text-sm text-slate-500" data-testid="check-inbox">
          We sent a sign-in link to <strong>{email}</strong>. Open it on this device to continue.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 py-24">
      <div className="flex flex-col gap-1 text-center">
        <h1 className="text-lg font-semibold text-slate-900">Sign in to Jury</h1>
        <p className="text-sm text-slate-500">We&apos;ll email you a one-time sign-in link.</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        {message && (
          <p className="text-sm text-red-600" data-testid="login-error">
            {message}
          </p>
        )}

        <Button type="submit" disabled={status === "sending"}>
          {status === "sending" ? "Sending link…" : "Send magic link"}
        </Button>
      </form>
    </div>
  );
}

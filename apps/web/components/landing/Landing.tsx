"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

import { SEATS, type Seat } from "@/lib/chairs";
import { buttonVariants } from "@/components/ui/button";
import { ChairTable } from "@/components/brand/ChairTable";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import { HowItWorks } from "./HowItWorks";
import { VsChatGPT } from "./VsChatGPT";

const START_HREF = "/projects/new";

const NAV = [
  { href: "#top", label: "Home" },
  { href: "#how-it-works", label: "How It Works" },
  { href: "#vs-chatgpt", label: "Vs ChatGPT" },
  { href: "#chair-chairman", label: "The Jurors" },
];

/** The public landing page for The Jury: hero boardroom, how it works,
 * the ChatGPT comparison and the closing call to action. */
export function Landing() {
  const [focusSeat, setFocusSeat] = useState<Seat | null>(null);
  const [sessionUnavailable, setSessionUnavailable] = useState(false);

  useEffect(() => {
    setSessionUnavailable(new URLSearchParams(window.location.search).get("session") === "unavailable");
  }, []);

  function jumpToSeat(seat: Seat) {
    setFocusSeat(seat);
    const el = document.getElementById(`chair-${seat}`);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    el?.focus({ preventScroll: true });
  }

  return (
    <div id="top" className="landing overflow-x-clip">
      <header className="sticky top-0 z-40 px-4 pt-3">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-6xl items-center justify-between gap-3 rounded-full border border-white/70 bg-white/60 py-2 pl-4 pr-2 backdrop-blur-xl"
        >
          <Logo />
          <ul className="hidden items-center gap-1 text-sm md:flex">
            {NAV.map((item, i) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className={cn(
                    "relative rounded-full px-4 py-2 transition-colors",
                    i === 0
                      ? "bg-white font-medium text-[#141A2E] shadow-sm after:absolute after:inset-x-4 after:-bottom-0.5 after:h-0.5 after:rounded-full after:bg-[#4F7BF7]"
                      : "text-[#6B7280] hover:text-[#141A2E]",
                  )}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <Link href={START_HREF} className={buttonVariants({ variant: "dark", size: "sm" })}>
              Get Started
            </Link>
          </div>
        </nav>
      </header>

      <main id="main">
        {sessionUnavailable && (
          <p role="alert" className="mx-auto mt-4 max-w-md rounded-full bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
            The Jury could not open a workspace session. Please try again shortly.
          </p>
        )}
        <section className="relative px-4 pt-10 sm:pt-14">
          <div className="rise mx-auto flex max-w-3xl flex-col items-center gap-4 text-center">
            <p className="text-[11px] font-medium uppercase tracking-[0.35em] text-[#6B7280] sm:text-xs">
              Five chairs. One clear verdict.
            </p>
            <h1 className="text-6xl font-semibold tracking-tight text-[#141A2E] sm:text-7xl">The Jury</h1>
            <p className="text-3xl font-semibold tracking-tight text-[#6B7A90] sm:text-4xl">Don&apos;t build it. Prove it.</p>
            <p className="max-w-xl text-base leading-relaxed text-[#6B7280] sm:text-lg">
              Pitch your idea. Our AI boardroom investigates with real evidence, challenges your
              assumptions, and gives you a clear, cited verdict.
            </p>
            <Link href={START_HREF} className={cn(buttonVariants({ variant: "dark", size: "lg" }), "group mt-1")}>
              Stress Test Your Idea
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden />
            </Link>
          </div>

          <div className="rise mx-auto -mt-[6%] max-w-6xl [animation-delay:150ms] sm:-mt-[9%]">
            <ChairTable
              callouts
              activeSeat={focusSeat}
              onSelect={jumpToSeat}
              selectLabel={(s) => `Meet The ${SEATS[s].name}`}
            />
            <p className="mt-2 pb-6 text-center text-xs text-[#9CA3AF] lg:hidden">Tap a juror to meet them</p>
          </div>
        </section>

        <HowItWorks focusSeat={focusSeat} onFocusSeat={setFocusSeat} />
        <VsChatGPT />

        <section className="px-4 py-20">
          <div className="relative mx-auto max-w-5xl overflow-hidden rounded-[2.5rem] bg-[#141A2E] px-6 py-16 text-center text-white sm:px-12">
            <div className="absolute -left-20 -top-24 h-72 w-72 rounded-full bg-[#4F7BF7] opacity-40 blur-3xl" />
            <div className="absolute -bottom-24 -right-16 h-72 w-72 rounded-full bg-[#7B5CF0] opacity-35 blur-3xl" />
            <div className="relative flex flex-col items-center gap-6">
              <h2 className="text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">
                The Jury is waiting for your idea!
              </h2>
              <p className="max-w-lg text-white/70">
                A few hundred words is all it takes. Walk out with a verdict, the evidence behind it,
                and the cheapest experiment to run next.
              </p>
              <Link
                href={START_HREF}
                className={cn(buttonVariants({ variant: "outline", size: "lg" }), "border-transparent bg-white text-[#141A2E]")}
              >
                Stress Test
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 pb-10 text-sm text-[#6B7280]">
        <Logo />
        <p>Evidence over opinion. © {new Date().getFullYear()} The Jury</p>
      </footer>
    </div>
  );
}

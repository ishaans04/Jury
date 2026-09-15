"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { CHAIR_FLOW, SEATS, type Seat } from "@/lib/chairs";
import type { Chair } from "@/lib/types";
import { MiniBot } from "@/components/brand/MiniBot";
import { cn } from "@/lib/utils";
import { PipelineFlow } from "./PipelineFlow";

const STEPS: { title: string; body: string; detail: string }[] = [
  {
    title: "Pitch",
    body: "Describe the idea in 200–2000 characters, with a target geography and segment.",
    detail: "The Jury detects your business archetype — marketplace, SaaS, D2C and more — so each chair knows which assumptions matter most.",
  },
  {
    title: "Hearing",
    body: "You confirm the assumptions the idea rests on before anything is investigated.",
    detail: "Every assumption is scored for criticality, uncertainty and falsifiability. Coverage gaps are flagged. Nothing proceeds without your sign-off.",
  },
  {
    title: "Investigation",
    body: "Five chairs retrieve and verify evidence in parallel, live.",
    detail: "Claims are fetched from real sources, tiered by credibility and cited. The Economics chair runs a deterministic solver: margins, LTV/CAC, sensitivity and breakpoints, with no model arithmetic.",
  },
  {
    title: "Cross-examination",
    body: "Chairs challenge each other, and your own claims, when the evidence disagrees.",
    detail: "Conflicts are typed — founder vs. world, chair vs. chair, scope gap — and every change of stance is recorded with the reason it moved.",
  },
  {
    title: "Verdict",
    body: "The Chairman rules Proceed, Pivot or Stop — or declares a hung jury.",
    detail: "Confidence is always shown with its formula and four components. When the gates fail, it refuses and names the three cheapest experiments.",
  },
  {
    title: "Living ledger",
    body: "Come back with real results. The ledger updates and shows what changed.",
    detail: "Each logged result re-runs only what it affects and writes an immutable version with a one-sentence causal diff.",
  },
];

const SEAT_ORDER: Seat[] = ["chairman", ...CHAIR_FLOW];

export function HowItWorks({
  focusSeat,
  onFocusSeat,
}: {
  focusSeat: Seat | null;
  onFocusSeat: (seat: Seat) => void;
}) {
  const [active, setActive] = useState(0);
  const step = STEPS[active];

  function selectChair(chair: Chair) {
    setActive(2);
    onFocusSeat(chair);
  }

  return (
    <section id="how-it-works" aria-labelledby="how-title" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-20">
      <div className="mx-auto mb-12 max-w-2xl text-center">
        <p className="mb-3 text-xs font-medium uppercase tracking-[0.3em] text-[#4F7BF7]">How it works</p>
        <h2 id="how-title" className="text-4xl font-semibold tracking-tight text-[#1B2033] sm:text-5xl">
          From pitch to verdict, with receipts.
        </h2>
        <p className="mt-4 text-[#6B7280]">Click any block to see what happens at that stage.</p>
      </div>

      <div className="rounded-[2rem] border border-white bg-gradient-to-b from-white/80 to-[#F7F8FB]/80 p-4 shadow-[0_30px_80px_-40px_rgba(27,32,51,0.25)] sm:p-8">
        <PipelineFlow activeStep={active} onSelectStep={setActive} onSelectChair={selectChair} />

        <div className="mt-8 grid items-center gap-6 border-t border-[#E9ECF2] pt-8 md:grid-cols-[auto_1fr_auto]">
          <span className="text-6xl font-semibold leading-none tracking-tight text-[#E3E7EE]" aria-hidden>
            0{active + 1}
          </span>
          <div key={active} className="rise flex flex-col gap-2" aria-live="polite">
            <h3 className="text-xl font-semibold text-[#1B2033]">{step.title}</h3>
            <p className="text-[#374151]">{step.body}</p>
            <p className="text-sm leading-relaxed text-[#6B7280]">{step.detail}</p>
            {active === 2 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {CHAIR_FLOW.map((c) => (
                  <a
                    key={c}
                    href={`#chair-${c}`}
                    onClick={() => onFocusSeat(c)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-[#E3E7EE] bg-white px-3 py-1 text-xs font-medium text-[#1B2033] hover:border-[#C5CCD8]"
                  >
                    <span className="h-2 w-2 rounded-full" style={{ background: SEATS[c].color }} />
                    {SEATS[c].name}
                  </a>
                ))}
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setActive((a) => (a + STEPS.length - 1) % STEPS.length)}
              aria-label="Previous step"
              className="grid h-11 w-11 place-items-center rounded-full border border-[#E3E7EE] bg-white text-[#1B2033] transition hover:-translate-x-0.5 hover:shadow-md"
            >
              <ChevronLeft className="h-5 w-5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => setActive((a) => (a + 1) % STEPS.length)}
              aria-label="Next step"
              className="grid h-11 w-11 place-items-center rounded-full bg-[#141A2E] text-white transition hover:translate-x-0.5 hover:shadow-md"
            >
              <ChevronRight className="h-5 w-5" aria-hidden />
            </button>
          </div>
        </div>
      </div>

      <h3 className="mb-6 mt-20 text-center text-3xl font-semibold tracking-tight text-[#1B2033]">Meet the jurors</h3>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SEAT_ORDER.map((seat) => {
          const meta = SEATS[seat];
          const highlighted = focusSeat === seat;
          return (
            <article
              key={seat}
              id={`chair-${seat}`}
              tabIndex={-1}
              onMouseEnter={() => onFocusSeat(seat)}
              aria-labelledby={`chair-${seat}-title`}
              className={cn(
                "relative flex scroll-mt-28 flex-col gap-4 overflow-hidden rounded-[2rem] border bg-white/90 p-6 transition-all duration-500 focus:outline-none",
                highlighted
                  ? "-translate-y-1 border-transparent shadow-[0_24px_60px_-24px_var(--seat)]"
                  : "border-white shadow-[0_12px_32px_-18px_rgba(27,32,51,0.2)]",
              )}
              style={{ "--seat": meta.color } as React.CSSProperties}
            >
              <div
                className="absolute inset-x-0 top-0 h-1 transition-opacity"
                style={{ background: meta.color, opacity: highlighted ? 1 : 0.3 }}
              />
              <div className="flex items-center gap-4">
                <div className="w-16 shrink-0">
                  <MiniBot seat={seat} />
                </div>
                <div>
                  <h4 id={`chair-${seat}-title`} className="text-lg font-semibold text-[#1B2033]">
                    The {meta.name}
                  </h4>
                  <p className="text-sm font-medium" style={{ color: meta.color }}>
                    {meta.question}
                  </p>
                </div>
              </div>
              <p className="text-sm text-[#4B5563]">{meta.summary}</p>
              <ul className="flex flex-col gap-2 text-sm text-[#374151]">
                {meta.checks.map((c) => (
                  <li key={c} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: meta.color }} />
                    {c}
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </section>
  );
}

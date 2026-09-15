import { Check, X } from "lucide-react";

const ROWS: { feature: string; llm: string; jury: string }[] = [
  {
    feature: "Evidence-backed retrieval",
    llm: "Answers from training data, which can be stale, generic or invented.",
    jury: "Chairs fetch live sources, verify each claim and tier its credibility.",
  },
  {
    feature: "Live arithmetic",
    llm: "The model estimates numbers in prose, and the maths can drift.",
    jury: "A deterministic solver computes margins, LTV/CAC, payback and breakpoints.",
  },
  {
    feature: "Cited audit trail",
    llm: "No record of where a claim came from, or how it was reached.",
    jury: "Every claim links to its source, and every run event is traceable.",
  },
  {
    feature: "Refusal gates",
    llm: "Always produces an answer, however thin the evidence.",
    jury: "Declares a hung jury below coverage and confidence gates, then names the experiments.",
  },
  {
    feature: "Adversarial review",
    llm: "One voice that tends to agree with whoever is asking.",
    jury: "Five chairs cross-examine each other and your own assertions.",
  },
  {
    feature: "Memory of your progress",
    llm: "Each chat starts over.",
    jury: "A versioned ledger shows exactly what changed when you log results.",
  },
];

export function VsChatGPT() {
  return (
    <section id="vs-chatgpt" aria-labelledby="vs-title" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-20">
      <div className="mb-10 max-w-2xl">
        <p className="mb-3 text-sm font-medium text-[#5B5BF7]">Vs ChatGPT</p>
        <h2 id="vs-title" className="font-display text-5xl leading-tight tracking-tight text-[#2A2620]">
          Advice sounds confident. Evidence is.
        </h2>
      </div>

      <div className="glass overflow-x-auto rounded-[2rem]">
        <table className="w-full min-w-[640px] border-collapse text-left text-sm">
          <caption className="sr-only">Generic LLM advice compared with The Jury</caption>
          <thead>
            <tr className="border-b border-[#EFE7D8]">
              <th scope="col" className="w-1/4 p-5 font-medium text-[#6B645A]">Capability</th>
              <th scope="col" className="w-[37.5%] p-5 font-medium text-[#6B645A]">Generic LLM advice</th>
              <th scope="col" className="w-[37.5%] bg-gradient-to-b from-[#EEF0FF] to-transparent p-5">
                <span className="font-display text-2xl text-[#2A2620]">The Jury</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.feature} className="border-b border-[#EFE7D8] last:border-0 transition-colors hover:bg-white/50">
                <th scope="row" className="p-5 font-semibold text-[#2A2620]">{row.feature}</th>
                <td className="p-5 text-[#6B645A]">
                  <span className="flex gap-3">
                    <X className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" aria-label="No" />
                    {row.llm}
                  </span>
                </td>
                <td className="bg-[#F4F3FF]/60 p-5 text-[#2A2620]">
                  <span className="flex gap-3">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-label="Yes" />
                    {row.jury}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

import {
  BarChart3,
  BookOpenText,
  Calculator,
  CircleDot,
  Link2,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Chair } from "@/lib/types";

/** Presentation metadata for the five investigating chairs plus the
 * Chairman who rules. Purely visual — the chair set itself is `CHAIRS`. */
export type Seat = Chair | "chairman";

export interface SeatMeta {
  key: Seat;
  name: string;
  tagline: string;
  color: string;
  icon: LucideIcon;
  question: string;
  summary: string;
  checks: string[];
}

export const SEATS: Record<Seat, SeatMeta> = {
  market: {
    key: "market",
    name: "Market",
    tagline: "Sizes the demand.",
    color: "#4F7BF7",
    icon: BarChart3,
    question: "Is the demand real, and big enough?",
    summary: "Sizes the opportunity from tiered, verifiable sources — never from vibes.",
    checks: [
      "Market size and growth pulled from cited tier-1 and tier-2 sources",
      "Competitor density and incumbents inside your exact geography",
      "Scope gaps when the data doesn't match your target segment",
    ],
  },
  customer: {
    key: "customer",
    name: "Customer",
    tagline: "Finds who pays.",
    color: "#2FA37F",
    icon: Users,
    question: "Will anyone actually pay for this?",
    summary: "Tests pain frequency and willingness to pay against real buyer behaviour.",
    checks: [
      "Evidence of willingness to pay at your asserted price",
      "How often the pain occurs, and what people use today",
      "Switching costs that quietly kill adoption",
    ],
  },
  precedent: {
    key: "precedent",
    name: "Precedent",
    tagline: "Reads the history.",
    color: "#7B5CF0",
    icon: BookOpenText,
    question: "Has this been tried, and what happened?",
    summary: "Finds the companies that walked this road before you and reads how it ended.",
    checks: [
      "Analogous startups, their outcomes and post-mortems",
      "Funding and shutdown patterns for the archetype",
      "Where the precedent diverges from your plan",
    ],
  },
  dependencies: {
    key: "dependencies",
    name: "Dependencies",
    tagline: "Maps the blockers.",
    color: "#E0578A",
    icon: Link2,
    question: "What must be true that you don't control?",
    summary: "Maps regulatory, platform and supplier dependencies that can block you.",
    checks: [
      "Licences, regulation and registry checks",
      "Platform, supplier and partner lock-in",
      "Adjacency feasibility, so a refuted blocker can become a pivot",
    ],
  },
  economics: {
    key: "economics",
    name: "Economics",
    tagline: "Tests the numbers.",
    color: "#F0873F",
    icon: Calculator,
    question: "Do the numbers survive contact?",
    summary: "Runs a deterministic unit-economics solver. The model never does arithmetic.",
    checks: [
      "Contribution margin, LTV/CAC and payback, solved live",
      "Sensitivity tornado ranking what moves the outcome most",
      "Breakpoints: the exact value where the business turns unviable",
    ],
  },
  chairman: {
    key: "chairman",
    name: "Chairman",
    tagline: "Weighs it. Decides.",
    color: "#3B4A7A",
    icon: CircleDot,
    question: "Proceed, pivot, or stop?",
    summary: "Weighs the record, publishes the confidence formula, and refuses when it must.",
    checks: [
      "Evidence confidence shown with all four components, never bare",
      "Refusal gates that return a hung jury instead of a guess",
      "The three cheapest experiments that would break the deadlock",
    ],
  },
};

/** The five investigating chairs, in pipeline order. */
export const CHAIR_FLOW: Chair[] = ["market", "customer", "precedent", "dependencies", "economics"];

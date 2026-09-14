/** Shared domain types, mirrored from `apps/api/jury/schemas/*` and
 * `supabase/migrations/0001_schema.sql`. Kept hand-written rather than
 * generated because the web app only ever touches a slice of the backend's
 * schema (PRD §13). */

export const CHAIRS = ["market", "customer", "precedent", "dependencies", "economics"] as const;
export type Chair = (typeof CHAIRS)[number];

export const CHAIR_LABELS: Record<Chair, string> = {
  market: "Market",
  customer: "Customer",
  precedent: "Precedent",
  dependencies: "Dependencies",
  economics: "Economics",
};

export const ARCHETYPES = [
  "marketplace",
  "subscription_saas",
  "d2c",
  "services",
  "ad_consumer",
  "hardware",
] as const;
export type Archetype = (typeof ARCHETYPES)[number];

export const ARCHETYPE_LABELS: Record<Archetype, string> = {
  marketplace: "Marketplace",
  subscription_saas: "Subscription SaaS",
  d2c: "D2C",
  services: "Services",
  ad_consumer: "Ad-supported consumer",
  hardware: "Hardware",
};

export type Criticality = "blocking" | "high" | "medium" | "low";
export type Uncertainty = "unknown" | "uncertain" | "likely" | "established";
export type Falsifiability = "testable_now" | "testable_costly" | "untestable";
export type Origin = "founder" | "discovered";

export const CRITICALITY_OPTIONS: Criticality[] = ["blocking", "high", "medium", "low"];
export const UNCERTAINTY_OPTIONS: Uncertainty[] = ["unknown", "uncertain", "likely", "established"];
export const FALSIFIABILITY_OPTIONS: Falsifiability[] = [
  "testable_now",
  "testable_costly",
  "untestable",
];

/** An assumption as it exists in the hearing: possibly not yet persisted
 * (`id` undefined for a founder-added row that hasn't been confirmed), and
 * possibly missing one or more of the three scoring axes — a founder-added
 * assumption starts with all three `null` so the confirm gate (F5) has
 * something real to block on. */
export interface HearingAssumption {
  id?: string;
  statement: string;
  class_key: string | null;
  origin: Origin;
  discovered_by: Chair | null;
  criticality: Criticality | null;
  uncertainty: Uncertainty | null;
  falsifiability: Falsifiability | null;
  asserted_variable?: string | null;
  asserted_value?: number | null;
  asserted_unit?: string | null;
}

export interface CoverageGap {
  key: string;
  crit_weight: number;
  question: string;
}

export interface SourceRef {
  id: string;
  canonical_url: string;
  domain: string;
  tier: number;
  title?: string | null;
}

export interface EvidenceItem {
  id: string;
  project_id: string;
  run_id: string;
  assumption_id: string;
  source_id: string;
  chair: Chair;
  direction: "supports" | "refutes";
  variable: string | null;
  value_num: number | null;
  value_min: number | null;
  value_max: number | null;
  unit: string | null;
  scope_geo: string;
  scope_segment: string;
  confidence: number;
  excerpt: string;
  created_at: string;
  sources?: SourceRef | SourceRef[] | null;
}

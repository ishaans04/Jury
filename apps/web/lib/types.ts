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

/* ── economics (PRD §16, `jury.schemas.economics`) ───────────────────── */

export type Provenance = "evidence_backed" | "founder_asserted";

export interface EconomicsParameter {
  value: number;
  unit: string;
  provenance: Provenance;
  source_id?: string | null;
  assumption_id?: string | null;
}

/** A breakpoint as the engine produces it — `sentence` is the rendered
 * form (PRD §16.5: "the business becomes loss-making above Rs 38 delivery
 * cost") and is what the UI shows verbatim; the other fields exist for
 * anything that needs the structured value instead. */
export interface Breakpoint {
  variable: string;
  threshold: number;
  direction: "above" | "below";
  unit: string;
  output: string;
  sentence: string;
}

/** A sensitivity row. `source` is resolved client-side (joined from the
 * parameter's `source_id` against `sources`) for evidence-backed rows only
 * — the backend's `SensitivityEntry` itself carries no source, just
 * provenance (PRD §16.6). */
export interface SensitivityEntry {
  variable: string;
  elasticity: number;
  provenance: Provenance;
  source?: SourceRef | null;
}

export interface ModelOutputs {
  contribution_margin: number;
  ltv: number;
  ltv_cac: number;
  payback_months: number | null;
  breakeven_volume_monthly: number | null;
}

export interface ModelRun {
  id: string;
  project_id: string;
  run_id: string;
  template_key: string;
  parameters: Record<string, EconomicsParameter>;
  outputs: ModelOutputs;
  breakpoints: Breakpoint[];
  sensitivity: SensitivityEntry[];
  viable: boolean;
  created_at: string;
}

/* ── verdict (PRD §9.3, `jury.schemas.verdict`) ──────────────────────── */

export type Decision = "PROCEED" | "PIVOT" | "STOP" | "HUNG_JURY";

/** PRD §9.3: "The UI always displays the four components alongside the
 * total." Every consumer of a `Verdict` must have these four in hand —
 * there is deliberately no path that carries `evidence_confidence` without
 * also carrying `components`. */
export interface ConfidenceComponents {
  coverage: number;
  mean_strength: number;
  contradiction: number;
  open_critical: number;
}

export interface FrictionItem {
  kind: ConflictKind;
  rule: string;
  status: ConflictStatus;
  resolution?: string | null;
}

export interface Verdict {
  id: string;
  run_id: string;
  project_id: string;
  decision: Decision;
  evidence_confidence: number;
  components: ConfidenceComponents;
  gate_triggered: string | null;
  friction: FrictionItem[];
  rationale: string;
  created_at: string;
}

/* ── experiments (PRD §16.6, `jury.schemas.experiment`) ──────────────── */

export const EXPERIMENT_METHODS = [
  "fake_door",
  "presale",
  "interview_script",
  "supplier_quote",
  "landing_ctr",
  "registry_check",
  "documented_proxy",
] as const;
export type ExperimentMethod = (typeof EXPERIMENT_METHODS)[number];

export const EXPERIMENT_METHOD_LABELS: Record<ExperimentMethod, string> = {
  fake_door: "Fake door",
  presale: "Presale",
  interview_script: "Interview script",
  supplier_quote: "Supplier quote",
  landing_ctr: "Landing page CTR",
  registry_check: "Registry check",
  documented_proxy: "Documented proxy",
};

export interface CriterionSpec {
  metric: string;
  comparator: ">=" | ">" | "<=" | "<" | "==";
  threshold: number;
  n?: number | null;
}

/** An experiment draft — `kill_criterion` is `NOT NULL` on the backend
 * schema (P9) and must never be omitted from a rendered card; `limitation`
 * is only populated for `documented_proxy` (spec §26.6, retention). */
export interface Experiment {
  id?: string;
  project_id?: string;
  assumption_id: string;
  target_variable: string | null;
  method: ExperimentMethod;
  instructions: string;
  kill_criterion: string;
  criterion_spec: CriterionSpec;
  est_cost: number | null;
  est_days: number | null;
  priority: number;
  status?: "proposed" | "running" | "passed" | "failed" | "abandoned";
  limitation?: string | null;
}

/* ── conflicts (PRD §22, `supabase/migrations/0001_schema.sql`) ──────── */

export type ConflictKind = "founder_vs_world" | "chair_vs_chair" | "no_evidence" | "scope_gap";
export type ConflictStatus = "open" | "resolved" | "conceded" | "unresolvable";
export type ConflictSeverity = "critical" | "high" | "medium" | "low";

export interface Conflict {
  id: string;
  project_id: string;
  run_id: string;
  assumption_id: string;
  kind: ConflictKind;
  left_ref: Record<string, unknown>;
  right_ref: Record<string, unknown> | null;
  rule: string;
  severity: ConflictSeverity;
  status: ConflictStatus;
  resolution?: string | null;
  created_at: string;
}

export interface PositionDeltaRecord {
  id: string;
  conflict_id: string;
  chair: Chair;
  before: string;
  after: string;
  reason: string;
  new_evidence_id?: string | null;
}

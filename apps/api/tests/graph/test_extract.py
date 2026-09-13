"""jury.graph.nodes.archetype / .extract / .coverage. Task 4.1.

Demo pitch: BillWise, GST-compliant invoicing for Indian SMBs -- the same
crowded, real-competitor category (Zoho Books, Vyapar, Tally) and the same
founder-asserted 499 INR/month price used by the Task 3.7 Market chair
fixtures (tests/chairs/test_market.py), so the same fixtures this task
records for the demo feed straight into the later boardroom demo run
(PRD §22's "crowded space where real contradictions and real corpses exist").

`CLASSES` below is the real `subscription_saas` row set from
db/seed/001_assumption_classes.sql, copied verbatim as the archetype's
checklist -- exactly the data `coverage_gaps` and the extraction prompt are
supposed to receive from the database in production. Copying it here (rather
than querying Postgres from a unit test) keeps this test suite offline and
DB-free like every other `jury.graph` unit test; `tests/test_seed_integrity.py`
is what checks the seed file itself matches the database.
"""
from jury.graph.nodes.archetype import detect_archetype
from jury.graph.nodes.coverage import coverage_gaps
from jury.graph.nodes.extract import extract_assumptions
from jury.schemas.enums import Archetype, Geo
from jury.tracing.events import MemoryTraceSink
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

PITCH_TYPICAL = (
    "BillWise is invoicing and GST-compliant billing software for Indian "
    "small businesses. We will charge SMBs 499 INR per month for unlimited "
    "invoices, targeting shop owners and freelancers who currently use "
    "Excel or Tally. GST filing is complex and error-prone for small teams, "
    "so we automate compliance and reconciliation. We plan to reach "
    "customers through WhatsApp referrals from chartered accountants, who "
    "currently onboard most small businesses onto accounting tools. Zoho "
    "Books, Vyapar and Tally already serve this market, but we believe our "
    "GST-first workflow and lower price will win switchers."
)

PITCH_PRICED = "We will charge 499 INR per month to Indian SMBs."

PITCH_NO_FIXTURE = "A pitch with no recorded fixture, to exercise the drop path."

# subscription_saas, verbatim from db/seed/001_assumption_classes.sql.
CLASSES: list[tuple[str, float, str]] = [
    ("saas.pain_severity", 1.0, "Is the pain acute enough to pay for?"),
    ("saas.wtp_above_cost", 1.0,
     "Does willingness to pay exceed delivered cost per account?"),
    ("saas.retention", 1.0, "Will accounts stay long enough to repay acquisition?"),
    ("saas.channel_cost", 1.0, "Is CAC recoverable within an acceptable payback?"),
    ("saas.buyer_identity", 0.6, "Is there a budget holder who can actually buy?"),
    ("saas.switching_cost", 0.6, "What makes them leave the current solution?"),
    ("saas.dependency_risk", 0.6,
     "Do required third parties permit this at viable cost?"),
    ("saas.data_compliance", 0.6, "Any data, privacy or regulatory constraint?"),
    ("saas.incumbency", 0.3, "Is the category already won or already a graveyard?"),
    ("saas.expansion", 0.3, "Is there an observable adjacency for expansion?"),
]


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


def _state(pitch: str) -> dict:
    return {"run_id": "r1", "project_id": "p1", "pitch": pitch}


# ── archetype detection ──────────────────────────────────────────────────

async def test_archetype_detection_returns_one_of_six_with_a_confidence():
    out = await detect_archetype(_state(PITCH_TYPICAL), transports=_transports(),
                                 trace=MemoryTraceSink())
    assert out["archetype"] in set(Archetype)
    assert 0.0 <= out["archetype_confidence"] <= 1.0


async def test_archetype_detection_also_infers_a_target_scope():
    """Spec §26.2: explicit at intake, pre-filled with an inferred default.

    Note: the brief's own snippet for this test reads `out["inferred_scope"]`,
    but the brief's interface list declares the RunState field (and the
    ArchetypeResult field carrying the value into it) as `target_scope`, and
    a node's return dict must use the RunState field name for the graph's
    merge step to do anything sensible with it. Treated the interface list
    as authoritative and used `target_scope` here; see the task report for
    the full note on this discrepancy.
    """
    out = await detect_archetype(_state(PITCH_TYPICAL), transports=_transports(),
                                 trace=MemoryTraceSink())
    assert out["target_scope"]["geo"] in set(Geo)


# ── extraction ────────────────────────────────────────────────────────────

async def test_extraction_produces_at_least_eight_assumptions_on_a_typical_pitch():
    """F5 acceptance criterion."""
    out = await extract_assumptions(_state(PITCH_TYPICAL), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    assert len(out["assumptions"]) >= 8


async def test_every_assumption_is_scored_on_all_three_axes():
    out = await extract_assumptions(_state(PITCH_TYPICAL), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    assert out["assumptions"]
    for a in out["assumptions"]:
        assert a["criticality"] in {"blocking", "high", "medium", "low"}
        assert a["uncertainty"] in {"unknown", "uncertain", "likely", "established"}
        assert a["falsifiability"] in {"testable_now", "testable_costly", "untestable"}


async def test_every_assumption_is_a_single_clause():
    """F5: 'each falsifiable and single-clause'.

    Tested as: one sentence, and no sequential conjunction. A naive " and "
    ban would wrongly reject noun phrases like "supply and demand", so
    conjunction density is reported as a metric by the Phase 7 extraction
    eval instead of gated here.
    """
    out = await extract_assumptions(_state(PITCH_TYPICAL), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    assert out["assumptions"]
    for a in out["assumptions"]:
        statement = a["statement"].strip()
        assert statement.count(".") <= 1, statement
        assert " and then " not in statement.lower(), statement
        assert ";" not in statement, statement


async def test_founder_origin_is_the_default_and_no_chair_is_named():
    """P2 + the DB check constraint: origin=founder implies discovered_by is null."""
    out = await extract_assumptions(_state(PITCH_TYPICAL), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    assert out["assumptions"]
    assert all(a["origin"] == "founder" and a.get("discovered_by") is None
               for a in out["assumptions"])


async def test_a_numeric_assertion_is_captured_as_variable_and_value():
    """This is what R3 needs. Without it, founder-vs-world can never fire."""
    out = await extract_assumptions(_state(PITCH_PRICED), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    priced = [a for a in out["assumptions"] if a.get("asserted_value")]
    assert priced
    assert priced[0]["asserted_variable"]
    assert priced[0]["asserted_value"] == 499


async def test_a_dropped_extraction_does_not_produce_a_partial_assumption():
    """Phase 2's repair loop returning None must not become a malformed row."""
    out = await extract_assumptions(_state(PITCH_NO_FIXTURE), transports=_transports(),
                                    classes=CLASSES, trace=MemoryTraceSink())
    assert out["assumptions"] == []


# ── coverage gaps (pure function) ────────────────────────────────────────

def test_coverage_gaps_name_every_silent_class():
    """F6. PRD §22 demo beat: 'your pitch is silent on supply liquidity and on
    regulatory'."""
    classes = [("m.demand", 1.0, "Do buyers look for this?"),
               ("m.supply", 1.0, "Will supply join?"),
               ("m.regulatory", 1.0, "Any licence needed?")]
    assumptions = [{"class_key": "m.demand"}]
    gaps = coverage_gaps(classes, assumptions)
    assert {g["key"] for g in gaps} == {"m.supply", "m.regulatory"}
    assert all(g["question"] for g in gaps)


def test_coverage_gaps_are_ordered_by_criticality_weight():
    """The founder should see the blocking silences first."""
    classes = [("a.low", 0.3, "q1"), ("a.block", 1.0, "q2")]
    gaps = coverage_gaps(classes, [])
    assert [g["key"] for g in gaps] == ["a.block", "a.low"]


def test_coverage_gap_order_is_stable_when_weights_tie():
    """Two classes sharing a weight must sort the same way on every call --
    by key, not by dict/set iteration order, which Python does not promise
    to be stable across runs for arbitrary objects."""
    classes = [("b.second", 1.0, "q"), ("a.first", 1.0, "q")]
    gaps = coverage_gaps(classes, [])
    assert [g["key"] for g in gaps] == ["a.first", "b.second"]


def test_no_gaps_when_every_class_is_addressed():
    classes = [("a.x", 1.0, "q")]
    assert coverage_gaps(classes, [{"class_key": "a.x"}]) == []

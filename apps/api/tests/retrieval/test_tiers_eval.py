"""Accuracy eval for rule-based tier assignment. PRD §19.2 pass bar: >=95%
on 100 labelled URLs. Because assignment is deterministic and rule-based
(never model-based), we aim for -- and expect -- 100% on this fixture.

The domain map here mirrors db/seed/002_domain_tiers.sql exactly. Production
loads that table from the database; this batch's `assign_tier` takes the map
as a plain argument (see PRD note in jury/retrieval/tiers.py), so the eval
constructs the same 33-row map by hand rather than hitting Postgres.
"""
import json
from pathlib import Path

from jury.retrieval.tiers import assign_tier

FIXTURE_PATH = Path(__file__).parents[2] / "evals" / "fixtures" / "tier_urls.json"

# Mirrors db/seed/002_domain_tiers.sql (33 domains, tiers 1-4).
DOMAIN_MAP = {
    # tier 1 -- regulators, registers, filings, stores, archives
    "sec.gov": 1, "rbi.org.in": 1, "mca.gov.in": 1, "gst.gov.in": 1,
    "eur-lex.europa.eu": 1, "gov.uk": 1, "ftc.gov": 1, "fda.gov": 1,
    "web.archive.org": 1, "play.google.com": 1, "apps.apple.com": 1,
    # tier 2 -- structured third-party data and official statistics
    "crunchbase.com": 2, "tracxn.com": 2, "data.worldbank.org": 2,
    "census.gov": 2, "statista.com": 2, "g2.com": 2, "capterra.com": 2,
    "trustpilot.com": 2,
    # tier 3 -- journalism, analysts, company blogs
    "techcrunch.com": 3, "theinformation.com": 3,
    "economictimes.indiatimes.com": 3, "yourstory.com": 3, "inc42.com": 3,
    "a16z.com": 3, "failory.com": 3, "autopsy.io": 3,
    # tier 4 -- community anecdote
    "reddit.com": 4, "news.ycombinator.com": 4, "indiehackers.com": 4,
    "producthunt.com": 4, "quora.com": 4, "stackoverflow.com": 4,
}


def _load_fixture() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_has_100_labelled_urls_across_all_four_tiers():
    rows = _load_fixture()
    assert len(rows) == 100
    from collections import Counter
    counts = Counter(r["expected_tier"] for r in rows)
    assert set(counts) == {1, 2, 3, 4}
    for tier in (1, 2, 3, 4):
        assert counts[tier] >= 20, f"tier {tier} is underrepresented: {counts}"


def test_rule_based_tier_assignment_meets_the_95_percent_accuracy_bar():
    rows = _load_fixture()
    mismatches = []
    for row in rows:
        got = assign_tier(row["url"], DOMAIN_MAP,
                          has_review_count=row.get("has_review_count", False))
        if got != row["expected_tier"]:
            mismatches.append((row["url"], row["expected_tier"], got))

    accuracy = (len(rows) - len(mismatches)) / len(rows)
    print(f"\ntier-assignment eval accuracy: {accuracy:.1%} "
          f"({len(rows) - len(mismatches)}/{len(rows)})")
    for url, expected, got in mismatches:
        print(f"  MISMATCH {url!r}: expected {expected}, got {got}")

    assert accuracy >= 0.95, (
        f"accuracy {accuracy:.1%} below the 95% pass bar; mismatches: {mismatches}"
    )

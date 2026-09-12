"""Closed sets. Every one of these is a hard constraint from PRD §12.2 / §6.1.

Free text where an enum belongs is the failure mode PRD §12.1 warns about:
"a free-text scope is uncomparable, and the conflict engine would flag
Rs 149 US-SMB against Rs 500 IN-enterprise as a contradiction."
"""
from enum import StrEnum


class Archetype(StrEnum):
    MARKETPLACE = "marketplace"
    SUBSCRIPTION_SAAS = "subscription_saas"
    D2C = "d2c"
    SERVICES = "services"
    AD_CONSUMER = "ad_consumer"
    HARDWARE = "hardware"


class Chair(StrEnum):
    MARKET = "market"
    CUSTOMER = "customer"
    PRECEDENT = "precedent"
    DEPENDENCIES = "dependencies"
    ECONOMICS = "economics"


class Direction(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"


class Geo(StrEnum):
    IN = "IN"; US = "US"; EU = "EU"; UK = "UK"
    SEA = "SEA"; MENA = "MENA"; LATAM = "LATAM"; GLOBAL = "GLOBAL"


class Segment(StrEnum):
    CONSUMER = "consumer"; PROSUMER = "prosumer"; SMB = "smb"
    MID_MARKET = "mid_market"; ENTERPRISE = "enterprise"; PUBLIC_SECTOR = "public_sector"


class Tier(StrEnum):
    FREE = "free"; ENTRY = "entry"; MID = "mid"
    PREMIUM = "premium"; ENTERPRISE = "enterprise"


class Criticality(StrEnum):
    BLOCKING = "blocking"; HIGH = "high"; MEDIUM = "medium"; LOW = "low"


class Uncertainty(StrEnum):
    UNKNOWN = "unknown"; UNCERTAIN = "uncertain"
    LIKELY = "likely"; ESTABLISHED = "established"


class Falsifiability(StrEnum):
    TESTABLE_NOW = "testable_now"
    TESTABLE_COSTLY = "testable_costly"
    UNTESTABLE = "untestable"


class AssumptionStatus(StrEnum):
    NO_EVIDENCE = "no_evidence"; UNCERTAIN = "uncertain"
    SUPPORTED = "supported"; REFUTED = "refuted"; CONTESTED = "contested"


class Origin(StrEnum):
    FOUNDER = "founder"; DISCOVERED = "discovered"


class ConflictKind(StrEnum):
    FOUNDER_VS_WORLD = "founder_vs_world"
    CHAIR_VS_CHAIR = "chair_vs_chair"
    NO_EVIDENCE = "no_evidence"
    SCOPE_GAP = "scope_gap"


class ConflictRule(StrEnum):
    R1 = "R1"; R2 = "R2"; R3 = "R3"; R4 = "R4"; R5 = "R5"


class ConflictStatus(StrEnum):
    OPEN = "open"; RESOLVED = "resolved"
    CONCEDED = "conceded"; UNRESOLVABLE = "unresolvable"


class Provenance(StrEnum):
    EVIDENCE_BACKED = "evidence_backed"
    FOUNDER_ASSERTED = "founder_asserted"


class Decision(StrEnum):
    PROCEED = "PROCEED"; PIVOT = "PIVOT"; STOP = "STOP"; HUNG_JURY = "HUNG_JURY"


class ExperimentMethod(StrEnum):
    FAKE_DOOR = "fake_door"; PRESALE = "presale"
    INTERVIEW_SCRIPT = "interview_script"; SUPPLIER_QUOTE = "supplier_quote"
    LANDING_CTR = "landing_ctr"; REGISTRY_CHECK = "registry_check"
    DOCUMENTED_PROXY = "documented_proxy"   # spec §26.6: retention is not testable in 30 days


class Comparator(StrEnum):
    GTE = ">="; GT = ">"; LTE = "<="; LT = "<"; EQ = "=="

"""Registered candidates and the feature builders that actually exist (spec sections 3.2 and 8.5).

A candidate name is not a label: evaluation and decisions dispatch to the builder registered here, and a
candidate whose evidence path does not exist is refused with UNIMPLEMENTED instead of silently running family A.
Horizons and ablations are the frozen registry of spec 8.5; anything else is a new trial that needs a new
registry version, so it is refused too.
"""
from __future__ import annotations

from dataclasses import dataclass

from .features import FEATURES, MARKET_FEATURES

FEATURE_SET_A = "features.set_a.v1"


class Unimplemented(ValueError):
    """The requested candidate, horizon or ablation has no registered implementation."""


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    id: str
    family: str
    feature_builder: str | None
    features: tuple[str, ...]
    horizons: tuple[int, ...]
    implemented: bool
    reason: str = ""
    event_records_required: bool = False


REGISTRY = {
    "A": CandidateSpec("A", "A", FEATURE_SET_A, FEATURES, (20, 60), True),
    "B": CandidateSpec("B", "B", None, (), (5, 20), False,
                       "family B needs the event registry and an announcement history (spec 3.2, 3.4); "
                       "prospective collection only", True),
    "C": CandidateSpec("C", "C", None, (), (5, 20), False,
                       "family C needs an owner-approved publisher set (spec 3.5)", True),
}

# Registered ablations of T3 (spec 8.5): without mom_12_1, without rev_5, stock features only.
ABLATIONS = {(): "none", ("mom_12_1",): "T3 without mom_12_1", ("rev_5",): "T3 without rev_5",
             tuple(sorted(MARKET_FEATURES)): "T3 stock features only"}


def require(candidate: str, h: int | None = None, ablate: tuple = ()) -> CandidateSpec:
    spec = REGISTRY.get(candidate)
    if spec is None:
        raise Unimplemented(f"UNKNOWN_CANDIDATE: {candidate!r} is not registered")
    if not spec.implemented:
        raise Unimplemented(f"UNIMPLEMENTED: candidate {candidate}: {spec.reason}")
    if h is not None and h not in spec.horizons:
        raise Unimplemented(f"UNREGISTERED_HORIZON: candidate {candidate} is registered for h in {list(spec.horizons)}")
    key = tuple(sorted(ablate))
    if key not in ABLATIONS:
        raise Unimplemented(f"UNREGISTERED_ABLATION: {list(ablate)}; registered: {[list(k) for k in ABLATIONS]}")
    if key and (candidate != "A" or h != 20):
        raise Unimplemented("UNREGISTERED_ABLATION: ablations are registered for candidate A at h = 20 only")
    return spec


def describe(spec: CandidateSpec, ablate: tuple = ()) -> dict:
    """What a report or decision actually used: builder, live columns, columns forced to zero, event records."""
    forced = sorted(ablate)
    return {"candidate": spec.id, "family": spec.family, "feature_builder": spec.feature_builder,
            "feature_columns": [f for f in spec.features if f not in forced], "ablated_columns": forced,
            "ablation": ABLATIONS.get(tuple(forced), "unregistered"), "event_records_used": 0,
            "event_records_required": spec.event_records_required}

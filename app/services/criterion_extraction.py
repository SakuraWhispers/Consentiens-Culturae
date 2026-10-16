"""Evidence -> criterion raw values (docs/architecture.md section 3).

ONE documented formula per criterion (single scoring_version). Rank-order and
hit-count appear as read-only diagnostics, never as scores. Deterministic:
no LLM, no randomness. Missing evidence yields None, never zero.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceRecord

FORMULAS = {
    "C1": "mean popularity over records with a popularity value",
    "C2": "1 - Jaccard(tag set vs union of other concepts' tag sets)",
    "C3": "share of non-error records with match_quality == exact",
    "C5": "share of all records with coverage_status == available",
}


def _usable(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    return [r for r in records if r.coverage_status not in ("error", "missing")]


def extract_raw_values(
    records_by_concept: dict[str, list[EvidenceRecord]],
) -> tuple[dict[str, dict[str, float | None]], dict[str, dict[str, float | int]]]:
    raw: dict[str, dict[str, float | None]] = {}
    diagnostics: dict[str, dict[str, float | int]] = {}

    tag_sets: dict[str, set[str]] = {}
    for cid, records in records_by_concept.items():
        tag_sets[cid] = {t for r in _usable(records) for t in r.tags}

    for cid, records in records_by_concept.items():
        usable = _usable(records)

        pops = [r.popularity for r in usable if r.popularity is not None]
        c1 = sum(pops) / len(pops) if pops else None

        own = tag_sets[cid]
        if own:
            others: set[str] = set()
            for other, tags in tag_sets.items():
                if other != cid:
                    others |= tags
            union = own | others
            c2 = 1.0 - (len(own & others) / len(union)) if union else 1.0
        else:
            c2 = None

        c3 = (
            sum(1 for r in usable if r.match_quality == "exact") / len(usable)
            if usable
            else None
        )
        c5 = (
            sum(1 for r in records if r.coverage_status == "available") / len(records)
            if records
            else None
        )

        raw[cid] = {"C1": c1, "C2": c2, "C3": c3, "C5": c5}
        diagnostics[cid] = {
            "c1_mean_popularity": c1 if c1 is not None else -1.0,
            "c1_rank_score": (
                sum(1.0 / (i + 1) for i, r in enumerate(usable) if r.popularity is not None)
                / max(1, sum(1 for r in usable if r.popularity is not None))
                if usable
                else -1.0
            ),
            "c1_hit_count": len(usable),
            "c2_tag_overlap": 1.0 - c2 if c2 is not None else -1.0,
            "c3_exact_share": c3 if c3 is not None else -1.0,
            "c5_available_share": c5 if c5 is not None else -1.0,
        }
    return raw, diagnostics


__all__ = ["FORMULAS", "extract_raw_values"]

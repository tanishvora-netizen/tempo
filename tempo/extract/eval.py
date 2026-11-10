"""Extraction eval on the synthetic labeled set (directive 7.7). Synthetic data; say so wherever shown.

Three readers of the core terms (discount, days, net, anchor, prox day):
- regex-only: the parser's value when the authoritative source has exactly one candidate, else "no answer".
- model-only: the model's raw reading, unverified.
- reconciled: Tempo's pipeline; only auto-accepted values count as answers, the rest are routed to review.
Metrics: exact-match accuracy over all invoices (no answer counts as wrong), precision over answered,
discount presence precision/recall, auto-accept coverage vs precision, the share of wrong model readings that
verification caught, accuracy per reconciliation bucket with its n, and everything by difficulty tag. The
held-out split is the invoices whose id hash falls in the last quarter (about 50 of 212); the prompt and the
parser were developed on the other three quarters.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from tempo.extract.reconcile import ACCEPTED, Reconciled
from tempo.extract.verify import as_record, model_terms
from tempo.llm.schemas import TermsExtraction
from tempo.models import Dataset, TermsRecord, TermsTruth

HOLDOUT_BUCKETS = 4


def is_holdout(invoice_id: str) -> bool:
    """Deterministic split by invoice-id hash: one bucket in four is held out."""
    return int(hashlib.sha256(invoice_id.encode()).hexdigest(), 16) % HOLDOUT_BUCKETS == 0


@dataclass(frozen=True)
class ReaderScore:
    n: int
    answered: int
    correct: int
    discount_tp: int
    discount_fp: int
    discount_fn: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def precision(self) -> float:
        return self.correct / self.answered if self.answered else 0.0

    @property
    def coverage(self) -> float:
        return self.answered / self.n if self.n else 0.0

    @property
    def discount_precision(self) -> float:
        d = self.discount_tp + self.discount_fp
        return self.discount_tp / d if d else 0.0

    @property
    def discount_recall(self) -> float:
        d = self.discount_tp + self.discount_fn
        return self.discount_tp / d if d else 0.0

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "answered": self.answered,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "coverage": self.coverage,
            "discount_precision": self.discount_precision,
            "discount_recall": self.discount_recall,
        }


def _score(pairs: list[tuple[TermsRecord | None, TermsRecord]]) -> ReaderScore:
    answered = sum(p is not None for p, _ in pairs)
    correct = sum(p is not None and p == t for p, t in pairs)
    tp = sum(p is not None and bool(p.discount_bps) and bool(t.discount_bps) for p, t in pairs)
    fp = sum(p is not None and bool(p.discount_bps) and not t.discount_bps for p, t in pairs)
    fn = sum((p is None or not p.discount_bps) and bool(t.discount_bps) for p, t in pairs)
    return ReaderScore(len(pairs), answered, correct, tp, fp, fn)


def readings(
    dataset: Dataset, reconciled: dict[str, Reconciled], extractions: dict[str, TermsExtraction | None]
) -> list[dict]:
    """Per invoice: truth and each reader's answer."""
    rows = []
    for inv in dataset.invoices:
        r = reconciled[inv.id]
        ext = extractions.get(inv.id)
        regex = r.terms.regex_values[0] if len(r.terms.regex_values) == 1 else None
        check = r.model_checks.get("terms")
        rows.append(
            {
                "id": inv.id,
                "tag": inv.tag,
                "holdout": is_holdout(inv.id),
                "truth": as_record(dataset.truth[inv.id].terms),
                "regex": regex,
                "model": model_terms(ext) if ext is not None else None,
                "model_verified": bool(check and check.verified),
                "reconciled": r.terms.value if r.terms.status in ACCEPTED else None,
                "status": r.terms.status,
                "expect_review": dataset.truth[inv.id].expect_review,
                "other_fields_correct": _other_fields_correct(r, dataset.truth[inv.id]),
            }
        )
    return rows


def evaluate_extraction(
    dataset: Dataset, reconciled: dict[str, Reconciled], extractions: dict[str, TermsExtraction | None]
) -> dict:
    """All extraction metrics, on the full set and the held-out split, plus by tag and by bucket."""
    rows = readings(dataset, reconciled, extractions)
    return {
        "synthetic": True,
        "all": _summary(rows),
        "holdout": _summary([r for r in rows if r["holdout"]]),
        "by_tag": {tag: _summary(group) for tag, group in sorted(_group(rows, "tag").items())},
        "has_model_outputs": any(r["model"] is not None for r in rows),
    }


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return groups


def _summary(rows: list[dict]) -> dict:
    out = {
        name: _score([(r[name], r["truth"]) for r in rows]).as_dict()
        for name in ("regex", "model", "reconciled")
    }
    wrong_model = [r for r in rows if r["model"] is not None and r["model"] != r["truth"]]
    rejected = sum(not r["model_verified"] for r in wrong_model)
    prevented = sum(r["reconciled"] != r["model"] for r in wrong_model)
    out["hallucination_catch"] = {
        "wrong_model_readings": len(wrong_model),
        "rejected_by_verification": rejected,
        "kept_out_of_plan": prevented,
        "rate": prevented / len(wrong_model) if wrong_model else None,
    }
    out["buckets"] = {
        status: {
            "n": len(g),
            "correct": sum(r["reconciled"] == r["truth"] for r in g if r["reconciled"] is not None),
        }
        for status, g in sorted(_group(rows, "status").items())
    }
    flagged = [r for r in rows if r["expect_review"]]
    out["expected_reviews_routed"] = {
        "n": len(flagged),
        "routed": sum(r["reconciled"] is None for r in flagged),
    }
    out["invoice_all_correct_rate"] = _all_fields_rate(rows)
    return out


def _all_fields_rate(rows: list[dict]) -> float:
    """Share of invoices with terms auto-accepted and right AND late fee, methods, surcharge, card flag right."""
    ok = sum(
        r["reconciled"] is not None and r["reconciled"] == r["truth"] and r["other_fields_correct"]
        for r in rows
    )
    return ok / len(rows) if rows else 0.0


def _other_fields_correct(r: Reconciled, truth: TermsTruth) -> bool:
    return (
        r.late_fee == truth.late_fee
        and set(r.accepted_methods) == set(truth.accepted_methods)
        and r.card_surcharge_bps == truth.card_surcharge_bps
        and r.card_discount_allowed == truth.card_discount_allowed
    )

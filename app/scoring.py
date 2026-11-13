"""Relevance scoring.

Every result gets a score in [0, 1] built from two signals:

budget fit (only when `targetBudget` is supplied)
    d = (price - target) / target          # relative deviation
    budget = 0.5 ** ((d / tolerance) ** 2)

    `tolerance` is the deviation at which the score halves. It is asymmetric:
    buyers usually stretch less above budget than they are happy to save
    below it, so over-budget homes decay faster.
        over budget:  tolerance = 10%  (+10% -> 0.50, +20% -> 0.06)
        under budget: tolerance = 25%  (-25% -> 0.50, -50% -> 0.06)
    A Gaussian-shaped curve (rather than linear) keeps near-misses close to
    1.0 and needs no hard cut-off.

recency
    recency = 0.5 ** (age_days / 30)

    Exponential decay with a 30-day half-life: brand-new listings score 1.0,
    a month-old listing 0.5, a quarter-old listing ~0.125. Future-dated
    listings (feed clock skew) are clamped to age 0.

combined
    with a target budget:    0.6 * budget + 0.4 * recency
    without a target budget: recency

Budget is weighted higher because price fit is the user's explicit intent;
recency is a tie-breaker that surfaces fresh inventory. Keyword/location
filters are hard filters and do not contribute to the score, so a score is
comparable across pages of the same query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

RECENCY_HALF_LIFE_DAYS = 30.0
BUDGET_TOLERANCE_OVER = 0.10
BUDGET_TOLERANCE_UNDER = 0.25
WEIGHT_BUDGET = 0.6
WEIGHT_RECENCY = 0.4


@dataclass(frozen=True, slots=True)
class Score:
    total: float
    budget: float | None
    recency: float


def budget_score(price: float, target: float) -> float:
    if target <= 0:
        raise ValueError("target budget must be positive")
    deviation = (price - target) / target
    tolerance = BUDGET_TOLERANCE_OVER if deviation > 0 else BUDGET_TOLERANCE_UNDER
    return 0.5 ** ((deviation / tolerance) ** 2)


def recency_score(listed: date, today: date) -> float:
    age_days = max(0, (today - listed).days)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def score_listing(price: float, listed: date, today: date, target: float | None) -> Score:
    recency = recency_score(listed, today)
    if target is None:
        return Score(total=recency, budget=None, recency=recency)
    budget = budget_score(price, target)
    return Score(
        total=WEIGHT_BUDGET * budget + WEIGHT_RECENCY * recency,
        budget=budget,
        recency=recency,
    )

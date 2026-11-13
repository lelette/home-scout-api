from datetime import date, timedelta

import pytest

from app.scoring import (
    BUDGET_TOLERANCE_OVER,
    BUDGET_TOLERANCE_UNDER,
    RECENCY_HALF_LIFE_DAYS,
    budget_score,
    recency_score,
    score_listing,
)

TODAY = date(2026, 10, 23)


def test_exact_budget_match_scores_one():
    assert budget_score(500_000, 500_000) == 1.0


def test_budget_score_halves_at_tolerance():
    assert budget_score(500_000 * (1 + BUDGET_TOLERANCE_OVER), 500_000) == pytest.approx(0.5)
    assert budget_score(500_000 * (1 - BUDGET_TOLERANCE_UNDER), 500_000) == pytest.approx(0.5)


def test_over_budget_penalized_more_than_under_budget():
    assert budget_score(550_000, 500_000) < budget_score(450_000, 500_000)


def test_budget_score_monotonic_away_from_target():
    prices = [500_000, 520_000, 560_000, 650_000, 1_000_000]
    scores = [budget_score(p, 500_000) for p in prices]
    assert scores == sorted(scores, reverse=True)
    prices = [500_000, 450_000, 350_000, 200_000, 1_000]
    scores = [budget_score(p, 500_000) for p in prices]
    assert scores == sorted(scores, reverse=True)


def test_budget_score_bounded():
    for price in (1, 100_000, 500_000, 10_000_000_000):
        assert 0.0 <= budget_score(price, 500_000) <= 1.0


def test_budget_score_rejects_non_positive_target():
    with pytest.raises(ValueError):
        budget_score(100, 0)


def test_recency_today_is_one_and_halves_per_half_life():
    assert recency_score(TODAY, TODAY) == 1.0
    assert recency_score(TODAY - timedelta(days=RECENCY_HALF_LIFE_DAYS), TODAY) == pytest.approx(0.5)
    assert recency_score(TODAY - timedelta(days=2 * RECENCY_HALF_LIFE_DAYS), TODAY) == pytest.approx(0.25)


def test_future_listing_date_is_clamped():
    assert recency_score(TODAY + timedelta(days=10), TODAY) == 1.0


def test_very_old_listing_approaches_zero_but_stays_non_negative():
    score = recency_score(date(1990, 1, 1), TODAY)
    assert 0.0 <= score < 1e-50


def test_without_target_score_is_recency_only():
    s = score_listing(123_456, TODAY - timedelta(days=30), TODAY, None)
    assert s.budget is None
    assert s.total == pytest.approx(0.5)


def test_combined_weights():
    s = score_listing(500_000, TODAY - timedelta(days=30), TODAY, 500_000)
    assert s.budget == 1.0
    assert s.recency == pytest.approx(0.5)
    assert s.total == pytest.approx(0.6 * 1.0 + 0.4 * 0.5)


def test_budget_fit_can_outrank_freshness():
    on_budget_old = score_listing(500_000, TODAY - timedelta(days=60), TODAY, 500_000)
    off_budget_new = score_listing(700_000, TODAY, TODAY, 500_000)
    assert on_budget_old.total > off_budget_new.total


def test_freshness_breaks_near_ties_in_budget():
    fresh = score_listing(505_000, TODAY, TODAY, 500_000)
    stale = score_listing(500_000, TODAY - timedelta(days=90), TODAY, 500_000)
    assert fresh.total > stale.total

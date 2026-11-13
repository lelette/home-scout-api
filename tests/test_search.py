from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from app.errors import ValidationError
from app.models import listing_from_dict
from app.repository import ListingRepository
from app.search import parse_search_params, search

from .conftest import FIXTURE_RECORDS, make_record

TODAY = date(2026, 10, 23)


@pytest.fixture
def repo():
    return ListingRepository(listing_from_dict(r) for r in FIXTURE_RECORDS)


def run(repo, **args):
    params = parse_search_params(MultiDict(args), default_page_size=20, max_page_size=100)
    return search(repo, params, TODAY)


def keys(result):
    return [s.listing.key for s in result.items]


def test_no_filters_returns_everything(repo):
    assert run(repo).total == len(FIXTURE_RECORDS)


def test_price_range_is_inclusive(repo):
    result = run(repo, minPrice="450000", maxPrice="550000")
    assert {s.listing.price for s in result.items} == {450000, 500000, 550000}


def test_min_bedrooms(repo):
    assert all(s.listing.bedrooms >= 4 for s in run(repo, minBedrooms="4").items)
    assert run(repo, minBedrooms="4").total == 2


def test_city_matches_across_inconsistent_sources(repo):
    result = run(repo, city="AUSTIN")
    assert ("MLS_B", "A1") in keys(result)  # stored as " austin " in the feed
    assert result.total == 4


def test_multiple_cities_are_ored(repo):
    assert run(repo, city="austin,dallas").total == 5
    assert run(repo, city=["Austin", "Denver"]).total == 5


def test_state_accepts_name_or_code(repo):
    assert run(repo, state="texas").total == run(repo, state="TX").total == 5
    assert run(repo, state="co").total == 1


def test_zip_plus_four_matches(repo):
    assert keys(run(repo, zip="78704-9999")) == [("MLS_B", "A1")]


def test_location_filters_combine_with_and(repo):
    assert run(repo, city="Austin", state="TX", zip="78701").total == 3
    assert run(repo, city="Austin", state="CO").total == 0


def test_unknown_city_returns_empty(repo):
    assert run(repo, city="Atlantis").total == 0


def test_keyword_is_case_insensitive_word_prefix(repo):
    result = run(repo, keyword="POOL")
    found = {s.listing.key for s in result.items}
    # "Pool", "pool" and "pools" match; "whirlpool" does not.
    assert found == {("MLS_A", "A1"), ("MLS_A", "A4"), ("MLS_B", "A1")}


def test_keyword_requires_all_terms(repo):
    assert keys(run(repo, keyword="pool kitchen")) == [("MLS_A", "A1")]
    assert run(repo, keyword="pool garage").total == 0


def test_keyword_with_regex_characters_is_literal(repo):
    assert run(repo, keyword="two-car").total == 1
    assert run(repo, keyword="(pool").total == 3  # punctuation is stripped, not a regex error


def test_status_and_source_filters(repo):
    assert run(repo, status="pending").total == 1
    assert run(repo, status="active,pending").total == 5
    assert run(repo, source="mls_b").total == 2


def test_filters_combine(repo):
    result = run(repo, city="Austin", minBedrooms="3", maxPrice="600000", keyword="garage")
    assert keys(result) == [("MLS_A", "A2")]


def test_relevance_without_budget_orders_by_recency(repo):
    dates = [s.listing.listed_date for s in run(repo).items]
    assert dates == sorted(dates, reverse=True)


def test_relevance_with_budget_prefers_price_fit(repo):
    result = run(repo, targetBudget="300000")
    assert result.items[0].listing.key == ("MLS_A", "A4")  # exactly on budget and recent
    scores = [s.score.total for s in result.items]
    assert scores == sorted(scores, reverse=True)


def test_price_and_date_sorts(repo):
    prices = [s.listing.price for s in run(repo, sort="price_asc").items]
    assert prices == sorted(prices)
    prices = [s.listing.price for s in run(repo, sort="price_desc").items]
    assert prices == sorted(prices, reverse=True)
    dates = [s.listing.listed_date for s in run(repo, sort="newest").items]
    assert dates == sorted(dates, reverse=True)


def test_ties_are_broken_deterministically():
    same = [make_record(id=f"T{i}", source=src) for i in range(3) for src in ("MLS_A", "MLS_B")]
    repo = ListingRepository(listing_from_dict(r) for r in reversed(same))
    first = keys(run(repo))
    assert first == sorted(first)
    assert keys(run(repo)) == first


def test_pagination_slices_and_counts(repo):
    page1 = run(repo, pageSize="4", page="1")
    page2 = run(repo, pageSize="4", page="2")
    assert len(page1.items) == 4 and len(page2.items) == 2
    assert page1.total_pages == 2
    assert not set(keys(page1)) & set(keys(page2))


def test_page_past_end_is_empty(repo):
    result = run(repo, page="99")
    assert result.items == [] and result.total == len(FIXTURE_RECORDS)


def test_empty_repository():
    result = run(ListingRepository())
    assert result.items == [] and result.total == 0 and result.total_pages == 0


@pytest.mark.parametrize("args, bad_field", [
    ({"minPrice": "abc"}, "minPrice"),
    ({"maxPrice": "-1"}, "maxPrice"),
    ({"minPrice": "500", "maxPrice": "100"}, "minPrice"),
    ({"minBedrooms": "2.5"}, "minBedrooms"),
    ({"minBedrooms": "-1"}, "minBedrooms"),
    ({"targetBudget": "0"}, "targetBudget"),
    ({"targetBudget": "lots"}, "targetBudget"),
    ({"page": "0"}, "page"),
    ({"pageSize": "101"}, "pageSize"),
    ({"pageSize": "0"}, "pageSize"),
    ({"state": "Narnia"}, "state"),
    ({"zip": "123"}, "zip"),
    ({"status": "withdrawn"}, "status"),
    ({"sort": "random"}, "sort"),
    ({"keyword": "!!!"}, "keyword"),
    ({"keyword": " ".join(f"w{i}" for i in range(11))}, "keyword"),
    ({"minprice": "100"}, "minprice"),  # typo'd parameter name
])
def test_invalid_params_raise(args, bad_field):
    with pytest.raises(ValidationError) as exc:
        parse_search_params(MultiDict(args), 20, 100)
    assert bad_field in {d["field"] for d in exc.value.details}


def test_all_param_errors_reported_together():
    with pytest.raises(ValidationError) as exc:
        parse_search_params(MultiDict({"minPrice": "x", "page": "0", "sort": "?"}), 20, 100)
    assert {d["field"] for d in exc.value.details} == {"minPrice", "page", "sort"}


def test_blank_params_and_cache_busters_are_ignored():
    params = parse_search_params(MultiDict({"minPrice": "", "city": "", "_": "1729"}), 20, 100)
    assert params.min_price is None and params.cities == ()


def test_target_budget_accepts_currency_format():
    params = parse_search_params(MultiDict({"targetBudget": "$500,000"}), 20, 100)
    assert params.target_budget == 500000


def test_heap_selection_matches_full_sort():
    """Early pages use heapq.nsmallest; results must equal a full sort."""
    records = [make_record(id=f"H{i:02d}", price=str(300_000 + (i * 7919) % 400_000),
                           listedDate=f"2026-{(i % 9) + 1:02d}-{(i % 27) + 1:02d}") for i in range(60)]
    repo = ListingRepository(listing_from_dict(r) for r in records)
    for sort in ("relevance", "price_asc", "price_desc", "newest"):
        everything = keys(run(repo, sort=sort, targetBudget="450000", pageSize="60"))
        paged = keys(run(repo, sort=sort, targetBudget="450000", pageSize="5", page="1"))
        paged += keys(run(repo, sort=sort, targetBudget="450000", pageSize="5", page="2"))
        assert paged == everything[:10]

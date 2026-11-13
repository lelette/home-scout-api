from datetime import date

import pytest

from app import normalize as norm


@pytest.mark.parametrize("raw, expected", [
    ("$450,000", 450000.0),
    ("450000", 450000.0),
    ("450,000.50", 450000.5),
    ("USD 450,000", 450000.0),
    (" $ 1,200,000 ", 1200000.0),
    (450000, 450000.0),
    (450000.0, 450000.0),
])
def test_parse_price_accepts_feed_formats(raw, expected):
    assert norm.parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "$", "-5", "0", "nan", "inf", True, None, [1]])
def test_parse_price_rejects_garbage(raw):
    with pytest.raises(ValueError):
        norm.parse_price(raw)


@pytest.mark.parametrize("raw, expected", [
    ("TX", "TX"), ("tx", "TX"), (" Tx. ", "TX"), ("Texas", "TX"), ("TEXAS", "TX"),
    ("new  york", "NY"), ("District of Columbia", "DC"), ("T.X.", "TX"),
])
def test_normalize_state(raw, expected):
    assert norm.normalize_state(raw) == expected


@pytest.mark.parametrize("raw", ["", "Texass", "ZZ", "Ontario"])
def test_normalize_state_rejects_unknown(raw):
    with pytest.raises(ValueError):
        norm.normalize_state(raw)


@pytest.mark.parametrize("raw, expected", [
    ("78701", "78701"), ("78701-1234", "78701"), ("78701 1234", "78701"), ("787011234", "78701"),
    (" 78701 ", "78701"), (78701, "78701"), (2134, "02134"),
])
def test_normalize_zip(raw, expected):
    assert norm.normalize_zip(raw) == expected


@pytest.mark.parametrize("raw", ["7870", "787012", "ABCDE", "78701-12", "", True])
def test_normalize_zip_rejects_invalid(raw):
    with pytest.raises(ValueError):
        norm.normalize_zip(raw)


@pytest.mark.parametrize("raw, expected", [
    ("austin", "Austin"), ("  SAN   antonio ", "San Antonio"), ("Round Rock,", "Round Rock"),
])
def test_normalize_city(raw, expected):
    assert norm.normalize_city(raw) == expected


def test_city_key_is_case_and_whitespace_insensitive():
    assert norm.city_key(" SAN  Antonio ") == norm.city_key("san antonio")


def test_normalize_city_rejects_blank():
    with pytest.raises(ValueError):
        norm.normalize_city("   ")


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-01", date(2026, 10, 1)),
    ("2026-10-01T15:30:00Z", date(2026, 10, 1)),
    ("2026-10-01T15:30:00+02:00", date(2026, 10, 1)),
])
def test_parse_iso_date(raw, expected):
    assert norm.parse_iso_date(raw) == expected


@pytest.mark.parametrize("raw", ["10/01/2026", "2026-13-01", "", 20261001])
def test_parse_iso_date_rejects_invalid(raw):
    with pytest.raises(ValueError):
        norm.parse_iso_date(raw)

"""Tests for searching stations with the Radio Browser API client."""

import re
from typing import Any

import pytest
from aioresponses import aioresponses
from multidict import MultiDictProxy
from syrupy.assertion import SnapshotAssertion

from radios import FilterBy, Order, RadioBrowser, RadioBrowserValidationError

from .conftest import API_URL, load_fixture

# Match the search endpoint regardless of the query string it gets.
SEARCH_URL = re.compile(rf"^{re.escape(API_URL)}/stations/search")


async def _search(
    responses: aioresponses, radios: RadioBrowser, **kwargs: Any
) -> MultiDictProxy[str]:
    """Run a search against a mocked API and return the query it sent."""
    responses.get(SEARCH_URL, payload=[])

    assert await radios.search(**kwargs) == []

    # aioresponses keys each request by method and the full URL, query string
    # included, so the one key holds exactly what was sent.
    ((_, url),) = responses.requests
    return url.query


async def test_search(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test searching returns the matching stations."""
    responses.get(SEARCH_URL, status=200, body=load_fixture("stations.json"))

    assert await radios.search(name="538") == snapshot


async def test_search_paging(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test search sends every paging and ordering parameter."""
    query = await _search(
        responses,
        radios,
        hide_broken=True,
        limit=10,
        offset=20,
        order=Order.VOTES,
        reverse=True,
    )

    assert query["hidebroken"] == "true"
    assert query["limit"] == "10"
    assert query["offset"] == "20"
    assert query["order"] == "votes"
    assert query["reverse"] == "true"


async def test_search_query_keys(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test search sends multi-word parameters in the casing the API expects."""
    query = await _search(
        responses,
        radios,
        name="538",
        name_exact=True,
        country_exact=True,
        state_exact=True,
        language_exact=True,
        tag_exact=True,
        bitrate_min=128,
        bitrate_max=320,
    )

    assert query["nameExact"] == "true"
    assert query["countryExact"] == "true"
    assert query["stateExact"] == "true"
    assert query["languageExact"] == "true"
    assert query["tagExact"] == "true"
    assert query["bitrateMin"] == "128"
    assert query["bitrateMax"] == "320"


async def test_search_filters(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test search sends the country code, state, language and tag filters."""
    query = await _search(
        responses,
        radios,
        name="radio",
        country_code="NL",
        state="Utrecht",
        language="dutch",
        tag="pop",
    )

    assert query["name"] == "radio"
    assert query["countrycode"] == "NL"
    assert query["state"] == "Utrecht"
    assert query["language"] == "dutch"
    assert query["tag"] == "pop"


async def test_search_more_filters(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test search sends the tag list, codec, HTTPS and info filters."""
    query = await _search(
        responses,
        radios,
        tag_list=["jazz", "blues"],
        codec="AAC",
        is_https=True,
        has_geo_info=False,
        has_extended_info=True,
    )

    assert query["tagList"] == "jazz,blues"
    assert query["codec"] == "AAC"
    assert query["is_https"] == "true"
    assert query["has_geo_info"] == "false"
    assert query["has_extended_info"] == "true"


async def test_search_geo(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test search sends a location and distance to search around."""
    query = await _search(
        responses, radios, geo_lat=52.37, geo_long=4.89, geo_distance=5000
    )

    assert query["geo_lat"] == "52.37"
    assert query["geo_long"] == "4.89"
    # probatio hands the body a float, which the API takes as well.
    assert query["geo_distance"] == "5000.0"


async def test_search_geo_distance(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test the results of a geo search carry their distance to the location."""
    stations = load_fixture("stations.json").replace(
        '"geo_distance": null', '"geo_distance": 1198.77', 1
    )
    responses.get(SEARCH_URL, status=200, body=stations)

    results = await radios.search(geo_lat=52.37, geo_long=4.89, geo_distance=5000)

    assert [station.distance for station in results] == [1198.77, None, None]


@pytest.mark.parametrize(
    "location", [{"geo_lat": 52.37}, {"geo_long": 4.89}, {"geo_distance": 5000.0}]
)
async def test_search_geo_incomplete(location: dict[str, Any]) -> None:
    """Test search rejects a location that misses its latitude or longitude."""
    radios = RadioBrowser(user_agent="PythonRadios/Tests")

    with pytest.raises(RadioBrowserValidationError, match="geo_lat and geo_long"):
        await radios.search(**location)


async def test_search_lowercases_tags_and_languages(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test tags and languages are sent in lowercase, other filters as given."""
    query = await _search(
        responses,
        radios,
        name="Radio 538",
        state="Utrecht",
        language="Dutch",
        tag="Pop",
        tag_list=["Jazz", "Blues"],
    )

    assert query["language"] == "dutch"
    assert query["tag"] == "pop"
    assert query["tagList"] == "jazz,blues"
    assert query["name"] == "Radio 538"
    assert query["state"] == "Utrecht"


@pytest.mark.parametrize(
    ("filter_by", "key", "value"),
    [
        (FilterBy.TAG_EXACT, "tag", "jazz"),
        (FilterBy.LANGUAGE, "language", "jazz"),
        (FilterBy.NAME, "name", "Jazz"),
    ],
)
async def test_search_filter_by_case(
    responses: aioresponses,
    radios: RadioBrowser,
    filter_by: FilterBy,
    key: str,
    value: str,
) -> None:
    """Test filter_by lowercases tag and language terms, and only those."""
    query = await _search(responses, radios, filter_by=filter_by, filter_term="Jazz")

    assert query[key] == value


@pytest.mark.parametrize(
    "location",
    [
        {"geo_lat": 91.0, "geo_long": 4.89},
        {"geo_lat": -90.5, "geo_long": 4.89},
        {"geo_lat": 52.37, "geo_long": 180.5},
        {"geo_lat": float("nan"), "geo_long": 4.89},
        {"geo_lat": 52.37, "geo_long": 4.89, "geo_distance": -5.0},
    ],
    ids=["north of 90", "south of -90", "east of 180", "not a number", "negative"],
)
async def test_search_geo_out_of_range(
    responses: aioresponses, radios: RadioBrowser, location: dict[str, Any]
) -> None:
    """Test a location that is not a coordinate is refused, the API fails on it."""
    with pytest.raises(RadioBrowserValidationError):
        await radios.search(**location)

    assert not responses.requests


async def test_search_omits_unset_filters(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test search does not send filters that are not set."""
    query = await _search(responses, radios)

    for key in (
        "name",
        "country",
        "countrycode",
        "state",
        "language",
        "tag",
        "tagList",
        "codec",
        "is_https",
        "has_geo_info",
        "has_extended_info",
        "geo_lat",
        "geo_long",
        "geo_distance",
    ):
        assert key not in query


@pytest.mark.parametrize(
    ("filter_by", "expected"),
    [
        (FilterBy.NAME, {"name": "term", "nameExact": "false"}),
        (FilterBy.NAME_EXACT, {"name": "term", "nameExact": "true"}),
        (FilterBy.CODEC_EXACT, {"codec": "term"}),
        (FilterBy.COUNTRY, {"country": "term", "countryExact": "false"}),
        (FilterBy.COUNTRY_EXACT, {"country": "term", "countryExact": "true"}),
        (FilterBy.COUNTRY_CODE_EXACT, {"countrycode": "term"}),
        (FilterBy.STATE, {"state": "term", "stateExact": "false"}),
        (FilterBy.STATE_EXACT, {"state": "term", "stateExact": "true"}),
        (FilterBy.LANGUAGE, {"language": "term", "languageExact": "false"}),
        (FilterBy.LANGUAGE_EXACT, {"language": "term", "languageExact": "true"}),
        (FilterBy.TAG, {"tag": "term", "tagExact": "false"}),
        (FilterBy.TAG_EXACT, {"tag": "term", "tagExact": "true"}),
    ],
)
async def test_search_filter_by(
    responses: aioresponses,
    radios: RadioBrowser,
    filter_by: FilterBy,
    expected: dict[str, str],
) -> None:
    """Test search turns filter_by into search query parameters."""
    # The explicit name and exact flags show that filter_by overrides them.
    query = await _search(
        responses,
        radios,
        filter_by=filter_by,
        filter_term="term",
        name="radio",
        name_exact=True,
        country_exact=True,
        state_exact=True,
        language_exact=True,
        tag_exact=True,
    )

    assert {key: query[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("filter_by", "filter_term"),
    [
        (FilterBy.UUID, "term"),
        (FilterBy.CODEC, "term"),
        (FilterBy.NAME, None),
    ],
)
async def test_search_filter_by_invalid(
    filter_by: FilterBy, filter_term: str | None
) -> None:
    """Test search rejects filter_by values it cannot send to the API."""
    radios = RadioBrowser(user_agent="PythonRadios/Tests")

    with pytest.raises(RadioBrowserValidationError, match="filter_"):
        await radios.search(filter_by=filter_by, filter_term=filter_term)

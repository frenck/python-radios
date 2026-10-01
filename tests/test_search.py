"""Tests for searching stations with the Radio Browser API client."""

import re
from typing import Any

import pytest
from aioresponses import aioresponses
from multidict import MultiDictProxy
from syrupy.assertion import SnapshotAssertion

from radios import FilterBy, RadioBrowser

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
    assert query["geo_distance"] == "5000"


@pytest.mark.parametrize(
    "location", [{"geo_lat": 52.37}, {"geo_long": 4.89}, {"geo_distance": 5000.0}]
)
async def test_search_geo_incomplete(location: dict[str, Any]) -> None:
    """Test search rejects a location that misses its latitude or longitude."""
    radios = RadioBrowser(user_agent="PythonRadios/Tests")

    with pytest.raises(ValueError, match="geo_lat and geo_long"):
        await radios.search(**location)


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

    with pytest.raises(ValueError, match="filter_"):
        await radios.search(filter_by=filter_by, filter_term=filter_term)

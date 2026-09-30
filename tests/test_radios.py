"""Asynchronous Python client for the Radio Browser API."""

# pylint: disable=protected-access
import re
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses
from multidict import MultiDictProxy

from radios.const import FilterBy
from radios.radio_browser import RadioBrowser

# Match the search endpoint regardless of the query string it gets.
SEARCH_URL = re.compile(r"^https://example\.com/json/stations/search")


async def test_json_request() -> None:
    """Test JSON response is handled correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "https://example.com/json/test",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            radio = RadioBrowser(session=session, user_agent="Test")
            radio._host = "example.com"
            response = await radio._request("test")
            assert response == '{"status": "ok"}'


async def _search(**kwargs: Any) -> MultiDictProxy[str]:
    """Run a search against a mocked API and return the query it sent."""
    with aioresponses() as mocked:
        mocked.get(SEARCH_URL, payload=[])
        async with aiohttp.ClientSession() as session:
            radio = RadioBrowser(session=session, user_agent="Test")
            radio._host = "example.com"
            assert await radio.search(**kwargs) == []

        # aioresponses keys each request by method and the full URL, query
        # string included, so the one key holds exactly what was sent.
        ((_, url),) = mocked.requests
        return url.query


async def test_search_query_keys() -> None:
    """Test search sends multi-word parameters in the casing the API expects."""
    query = await _search(
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


async def test_search_filters() -> None:
    """Test search sends the country code, state, language and tag filters."""
    query = await _search(
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


async def test_search_omits_unset_filters() -> None:
    """Test search does not send filters that are not set."""
    query = await _search()

    for key in ("name", "country", "countrycode", "state", "language", "tag"):
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
async def test_search_filter_by(filter_by: FilterBy, expected: dict[str, str]) -> None:
    """Test search turns filter_by into search query parameters."""
    # The explicit name and exact flags show that filter_by overrides them.
    query = await _search(
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
    radio = RadioBrowser(user_agent="Test")

    with pytest.raises(ValueError, match="filter_"):
        await radio.search(filter_by=filter_by, filter_term=filter_term)

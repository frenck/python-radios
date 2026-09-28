"""Asynchronous Python client for the Radio Browser API."""

# pylint: disable=protected-access
import aiohttp
import pytest
from aiohttp import web
from aresponses import ResponsesMockServer

from radios.const import FilterBy
from radios.radio_browser import RadioBrowser


async def test_json_request(aresponses: ResponsesMockServer) -> None:
    """Test JSON response is handled correctly."""
    aresponses.add(
        "example.com",
        "/json/test",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        radio = RadioBrowser(session=session, user_agent="Test")
        radio._host = "example.com"
        response = await radio._request("test")
        assert response == '{"status": "ok"}'


async def _search(aresponses: ResponsesMockServer, **kwargs: object) -> web.Request:
    """Run a search against a mocked API and return the request it made."""
    requests: list[web.Request] = []

    async def handler(request: web.Request) -> web.Response:
        requests.append(request)
        return web.json_response([])

    aresponses.add("example.com", "/json/stations/search", "GET", handler)
    async with aiohttp.ClientSession() as session:
        radio = RadioBrowser(session=session, user_agent="Test")
        radio._host = "example.com"
        assert await radio.search(**kwargs) == []  # type: ignore[arg-type]
    return requests[0]


async def test_search_query_keys(aresponses: ResponsesMockServer) -> None:
    """Test search sends multi-word parameters in the casing the API expects."""
    request = await _search(
        aresponses,
        name="538",
        name_exact=True,
        country_exact=True,
        state_exact=True,
        language_exact=True,
        tag_exact=True,
        bitrate_min=128,
        bitrate_max=320,
    )

    assert request.query["nameExact"] == "true"
    assert request.query["countryExact"] == "true"
    assert request.query["stateExact"] == "true"
    assert request.query["languageExact"] == "true"
    assert request.query["tagExact"] == "true"
    assert request.query["bitrateMin"] == "128"
    assert request.query["bitrateMax"] == "320"


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
    aresponses: ResponsesMockServer, filter_by: FilterBy, expected: dict[str, str]
) -> None:
    """Test search turns filter_by into search query parameters."""
    # The explicit name and exact flags show that filter_by overrides them.
    request = await _search(
        aresponses,
        filter_by=filter_by,
        filter_term="term",
        name="radio",
        name_exact=True,
        country_exact=True,
        state_exact=True,
        language_exact=True,
        tag_exact=True,
    )

    assert {key: request.query[key] for key in expected} == expected


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

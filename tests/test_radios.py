"""Asynchronous Python client for the Radio Browser API."""

# pylint: disable=protected-access
import aiohttp
from aiohttp import web
from aresponses import ResponsesMockServer

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


async def test_search_filters(aresponses: ResponsesMockServer) -> None:
    """Test search sends the country code, state, language and tag filters."""
    requests: list[web.Request] = []

    async def handler(request: web.Request) -> web.Response:
        requests.append(request)
        return web.json_response([])

    aresponses.add("example.com", "/json/stations/search", "GET", handler)
    async with aiohttp.ClientSession() as session:
        radio = RadioBrowser(session=session, user_agent="Test")
        radio._host = "example.com"
        stations = await radio.search(
            name="radio",
            country_code="NL",
            state="Utrecht",
            language="dutch",
            tag="pop",
        )

    assert stations == []
    assert requests[0].query["name"] == "radio"
    assert requests[0].query["countrycode"] == "NL"
    assert requests[0].query["state"] == "Utrecht"
    assert requests[0].query["language"] == "dutch"
    assert requests[0].query["tag"] == "pop"


async def test_search_omits_unset_filters(aresponses: ResponsesMockServer) -> None:
    """Test search does not send filters that are not set."""
    requests: list[web.Request] = []

    async def handler(request: web.Request) -> web.Response:
        requests.append(request)
        return web.json_response([])

    aresponses.add("example.com", "/json/stations/search", "GET", handler)
    async with aiohttp.ClientSession() as session:
        radio = RadioBrowser(session=session, user_agent="Test")
        radio._host = "example.com"
        await radio.search()

    for key in ("name", "countrycode", "state", "language", "tag"):
        assert key not in requests[0].query

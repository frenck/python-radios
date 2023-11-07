"""Asynchronous Python client for the Radio Browser API."""
# pylint: disable=protected-access
import aiohttp
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

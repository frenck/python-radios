"""Asynchronous Python client for the Radio Browser API."""

# pylint: disable=protected-access
import aiohttp
from aioresponses import aioresponses

from radios.radio_browser import RadioBrowser


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

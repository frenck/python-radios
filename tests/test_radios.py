"""Tests for the request handling of the Radio Browser API client."""

# pylint: disable=protected-access
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from radios import (
    RadioBrowser,
    RadioBrowserConnectionError,
    RadioBrowserConnectionTimeoutError,
    RadioBrowserError,
)

from .conftest import API_URL


@pytest.fixture
def backoff_sleep() -> Generator[AsyncMock, None, None]:
    """Skip the real waits between retries, and count them instead."""
    with patch("backoff._async.asyncio.sleep", new=AsyncMock()) as sleep:
        yield sleep


async def test_json_request(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test a JSON response is returned as text."""
    responses.get(
        f"{API_URL}/test",
        status=200,
        body='{"status": "ok"}',
        content_type="application/json",
    )

    assert await radios._request("test") == '{"status": "ok"}'


async def test_request_headers(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test the user agent and accept headers are sent with each request."""
    responses.get(f"{API_URL}/test", status=200, payload={})

    await radios._request("test")

    ((request,),) = responses.requests.values()
    assert request.kwargs["headers"] == {
        "User-Agent": "PythonRadios/Tests",
        "Accept": "application/json",
    }


async def test_request_boolean_params(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test booleans are sent as the lowercase strings the API expects."""
    responses.get(f"{API_URL}/test?on=true&off=false&limit=5", status=200, payload={})

    await radios._request("test", params={"on": True, "off": False, "limit": 5})

    ((_, url),) = responses.requests
    assert url.query == {"on": "true", "off": "false", "limit": "5"}


async def test_unexpected_content_type(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a response that is not JSON raises a Radio Browser error."""
    responses.get(
        f"{API_URL}/test",
        status=200,
        body="Not JSON",
        content_type="text/plain",
    )

    with pytest.raises(RadioBrowserError) as error:
        await radios._request("test")

    assert error.value.args == (200, {"message": "Not JSON"})


@pytest.mark.usefixtures("backoff_sleep")
async def test_timeout(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test a timeout raises a timeout error and forgets the API host."""
    responses.get(f"{API_URL}/test", exception=TimeoutError(), repeat=True)

    with pytest.raises(RadioBrowserConnectionTimeoutError):
        await radios._request("test")

    assert radios._host is None


@pytest.mark.usefixtures("backoff_sleep")
async def test_timeout_is_connection_error(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test the timeout error can be caught as a connection error."""
    responses.get(f"{API_URL}/test", exception=TimeoutError(), repeat=True)

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")


@pytest.mark.usefixtures("backoff_sleep")
async def test_connection_error(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test a client error raises a connection error and forgets the API host."""
    responses.get(
        f"{API_URL}/test", exception=aiohttp.ClientConnectionError(), repeat=True
    )

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    assert radios._host is None


async def test_connection_error_retries(
    responses: aioresponses, radios: RadioBrowser, backoff_sleep: AsyncMock
) -> None:
    """Test a failing request is tried five times before giving up."""
    responses.get(
        f"{API_URL}/test", exception=aiohttp.ClientConnectionError(), repeat=True
    )

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    ((request_calls),) = responses.requests.values()
    assert len(request_calls) == 5
    assert backoff_sleep.await_count == 4


async def test_connection_error_recovers(
    responses: aioresponses,
    radios: RadioBrowser,
    backoff_sleep: AsyncMock,
    dns_resolver: MagicMock,
) -> None:
    """Test a request that fails once succeeds on the retry."""
    responses.get(f"{API_URL}/test", exception=aiohttp.ClientConnectionError())
    responses.get(f"{API_URL}/test", status=200, payload={"status": "ok"})

    assert await radios._request("test") == '{"status": "ok"}'

    # The failure forgets the host, so the retry looks it up again.
    assert backoff_sleep.await_count == 1
    dns_resolver.return_value.query.assert_awaited_once_with(
        "_api._tcp.radio-browser.info", "SRV"
    )


async def test_host_lookup(responses: aioresponses, dns_resolver: MagicMock) -> None:
    """Test the API host is looked up through DNS SRV records, and cached."""
    responses.get(f"{API_URL}/test", status=200, payload={}, repeat=True)

    async with RadioBrowser(user_agent="PythonRadios/Tests") as radios:
        await radios._request("test")
        await radios._request("test")

    assert radios._host == "example.com"
    dns_resolver.return_value.query.assert_awaited_once_with(
        "_api._tcp.radio-browser.info", "SRV"
    )


async def test_internal_session(responses: aioresponses) -> None:
    """Test a session created by the client is closed by the client."""
    responses.get(f"{API_URL}/test", status=200, payload={})

    async with RadioBrowser(user_agent="PythonRadios/Tests") as radios:
        radios._host = "example.com"
        await radios._request("test")
        session = radios.session

    assert session is not None
    assert session.closed


async def test_external_session(responses: aioresponses) -> None:
    """Test a session passed in by the caller is left open."""
    responses.get(f"{API_URL}/test", status=200, payload={})

    async with aiohttp.ClientSession() as session:
        async with RadioBrowser(
            user_agent="PythonRadios/Tests", session=session
        ) as radios:
            radios._host = "example.com"
            await radios._request("test")

        assert not session.closed


async def test_close_without_session() -> None:
    """Test closing a client that never made a request does nothing."""
    radios = RadioBrowser(user_agent="PythonRadios/Tests")

    await radios.close()

    assert radios.session is None

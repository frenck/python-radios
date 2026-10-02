"""Tests for the request handling of the Radio Browser API client."""

# pylint: disable=protected-access
import asyncio
import re
from collections.abc import Awaitable, Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiodns.error import DNSError
from aioresponses import aioresponses
from pycares import QUERY_CLASS_IN, QUERY_TYPE_CNAME, CNAMERecordData, DNSRecord

from radios import (
    RadioBrowser,
    RadioBrowserConnectionError,
    RadioBrowserConnectionTimeoutError,
    RadioBrowserError,
)

from .conftest import API_URL, srv_result


@pytest.fixture
def retry_sleep() -> Generator[AsyncMock, None, None]:
    """Skip the real waits between retries, and count them instead."""
    with patch("radios.radio_browser.sleep", new=AsyncMock()) as sleep:
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


async def test_undecodable_response(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a body that does not match its encoding raises a Radio Browser error."""
    responses.get(
        f"{API_URL}/test",
        body=b'{"name": "\xff"}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    with pytest.raises(RadioBrowserError, match="Unexpected response") as error:
        await radios._request("test")

    assert not isinstance(error.value, RadioBrowserConnectionError)
    assert isinstance(error.value.__cause__, UnicodeDecodeError)


@pytest.mark.usefixtures("retry_sleep")
async def test_timeout_while_reading_body(
    responses: aioresponses, radios: RadioBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test a response body that never arrives runs into the request timeout."""
    responses.get(f"{API_URL}/test", status=200, payload={}, repeat=True)

    async def stalled_text(*_args: object, **_kwargs: object) -> str:
        await asyncio.Event().wait()
        return "{}"  # pragma: no cover

    monkeypatch.setattr(aiohttp.ClientResponse, "text", stalled_text)
    radios.request_timeout = 0.01

    with pytest.raises(RadioBrowserConnectionTimeoutError):
        await radios._request("test")


@pytest.mark.usefixtures("retry_sleep")
async def test_timeout(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test a timeout raises a timeout error and forgets the API host."""
    responses.get(f"{API_URL}/test", exception=TimeoutError(), repeat=True)

    with pytest.raises(RadioBrowserConnectionTimeoutError):
        await radios._request("test")

    assert radios._host is None


@pytest.mark.usefixtures("retry_sleep")
async def test_timeout_is_connection_error(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test the timeout error can be caught as a connection error."""
    responses.get(f"{API_URL}/test", exception=TimeoutError(), repeat=True)

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")


@pytest.mark.usefixtures("retry_sleep")
async def test_connection_error(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test a client error raises a connection error and forgets the API host."""
    responses.get(
        f"{API_URL}/test", exception=aiohttp.ClientConnectionError(), repeat=True
    )

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    assert radios._host is None


async def test_connection_error_retries(
    responses: aioresponses, radios: RadioBrowser, retry_sleep: AsyncMock
) -> None:
    """Test a failing request is tried five times before giving up."""
    responses.get(
        f"{API_URL}/test", exception=aiohttp.ClientConnectionError(), repeat=True
    )

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    ((request_calls),) = responses.requests.values()
    assert len(request_calls) == 5
    assert retry_sleep.await_count == 4


async def test_retry_delays(
    responses: aioresponses, radios: RadioBrowser, retry_sleep: AsyncMock
) -> None:
    """Test the wait between attempts grows exponentially, with jitter."""
    responses.get(
        f"{API_URL}/test", exception=aiohttp.ClientConnectionError(), repeat=True
    )

    # A distinct "random" value per attempt shows the wait comes from the
    # jitter, and not from the bounds alone.
    jitter = [0.3, 1.1, 2.5, 7.9]
    with (
        patch("radios.radio_browser.random.uniform", side_effect=jitter) as uniform,
        pytest.raises(RadioBrowserConnectionError),
    ):
        await radios._request("test")

    assert [call.args for call in uniform.call_args_list] == [
        (0, 1),
        (0, 2),
        (0, 4),
        (0, 8),
    ]
    assert [call.args[0] for call in retry_sleep.await_args_list] == jitter


async def test_connection_error_recovers(
    responses: aioresponses,
    radios: RadioBrowser,
    retry_sleep: AsyncMock,
    dns_resolver: MagicMock,
) -> None:
    """Test a request that fails once succeeds on the retry."""
    responses.get(f"{API_URL}/test", exception=aiohttp.ClientConnectionError())
    responses.get(f"{API_URL}/test", status=200, payload={"status": "ok"})

    assert await radios._request("test") == '{"status": "ok"}'

    # The failure forgets the host, so the retry looks it up again.
    assert retry_sleep.await_count == 1
    dns_resolver.return_value.query_dns.assert_awaited_once_with(
        "_api._tcp.radio-browser.info", "SRV"
    )


async def test_client_error_is_not_retried(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a 4xx response raises right away, without retrying or a new host."""
    responses.get(f"{API_URL}/test", status=404, repeat=True)

    with pytest.raises(RadioBrowserError) as error:
        await radios._request("test")

    assert not isinstance(error.value, RadioBrowserConnectionError)
    assert error.value.args[0] == 404
    ((request_calls),) = responses.requests.values()
    assert len(request_calls) == 1
    assert radios._host == "example.com"


async def test_server_error_is_retried(
    responses: aioresponses, radios: RadioBrowser, retry_sleep: AsyncMock
) -> None:
    """Test a 5xx response is retried, since another server may do better."""
    responses.get(f"{API_URL}/test", status=503, repeat=True)

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    ((request_calls),) = responses.requests.values()
    assert len(request_calls) == 5
    assert retry_sleep.await_count == 4
    assert radios._host is None


async def test_host_lookup(responses: aioresponses, dns_resolver: MagicMock) -> None:
    """Test the API host is looked up through DNS SRV records, and cached."""
    responses.get(f"{API_URL}/test", status=200, payload={}, repeat=True)

    async with RadioBrowser(user_agent="PythonRadios/Tests") as radios:
        await radios._request("test")
        await radios._request("test")

    assert radios._host == "example.com"
    dns_resolver.return_value.query_dns.assert_awaited_once_with(
        "_api._tcp.radio-browser.info", "SRV"
    )


async def test_host_lookup_picks_a_server(
    responses: aioresponses, radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test the API host is one of the SRV targets, ignoring other records."""
    responses.get(re.compile(r"^https://[a-z]+\.example\.com/json/test$"), payload={})

    result = srv_result("one.example.com", "two.example.com")
    result.answer.append(
        DNSRecord(
            name="_api._tcp.radio-browser.info",
            type=QUERY_TYPE_CNAME,
            record_class=QUERY_CLASS_IN,
            ttl=300,
            data=CNAMERecordData(cname="three.example.com"),
        )
    )
    dns_resolver.return_value.query_dns.return_value = result
    radios._host = None

    # Reverse the "random" order, so always taking the first one would fail.
    with patch(
        "radios.radio_browser.random.shuffle", side_effect=lambda hosts: hosts.reverse()
    ) as shuffle:
        await radios._request("test")

    shuffle.assert_called_once()
    assert radios._host == "two.example.com"
    assert radios._hosts == ["one.example.com"]
    ((_, url),) = responses.requests
    assert url.host == "two.example.com"


@pytest.mark.usefixtures("retry_sleep")
async def test_failed_server_is_not_tried_again(
    responses: aioresponses, radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test a retry goes to the next server, instead of the one that failed."""
    responses.get(
        "https://one.example.com/json/test", exception=aiohttp.ClientConnectionError()
    )
    responses.get("https://two.example.com/json/test", payload={"status": "ok"})
    dns_resolver.return_value.query_dns.return_value = srv_result(
        "one.example.com", "two.example.com"
    )
    radios._host = None

    with patch("radios.radio_browser.random.shuffle"):
        assert await radios._request("test") == '{"status": "ok"}'

    assert radios._host == "two.example.com"
    dns_resolver.return_value.query_dns.assert_awaited_once()


@pytest.mark.usefixtures("retry_sleep")
async def test_servers_are_looked_up_again_once_all_failed(
    responses: aioresponses, radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test the servers are looked up again after every one of them failed."""
    responses.get(
        re.compile(r"^https://[a-z]+\.example\.com/json/test$"),
        exception=aiohttp.ClientConnectionError(),
        repeat=True,
    )
    dns_resolver.return_value.query_dns.return_value = srv_result(
        "one.example.com", "two.example.com"
    )
    radios._host = None

    with pytest.raises(RadioBrowserConnectionError):
        await radios._request("test")

    # Five attempts over two servers: one, two, look up, one, two, look up, one.
    assert dns_resolver.return_value.query_dns.await_count == 3


@pytest.mark.parametrize(
    "lookup",
    [
        {"side_effect": DNSError(11, "Could not contact DNS servers")},
        {"return_value": srv_result()},
    ],
    ids=["dns error", "no servers"],
)
async def test_host_lookup_falls_back(
    responses: aioresponses,
    radios: RadioBrowser,
    dns_resolver: MagicMock,
    lookup: dict[str, Any],
) -> None:
    """Test a failing SRV lookup falls back to the host name of all servers."""
    responses.get("https://all.api.radio-browser.info/json/test", payload={"a": 1})
    dns_resolver.return_value.query_dns = AsyncMock(**lookup)
    radios._host = None

    assert await radios._request("test") == '{"a": 1}'
    assert radios._host == "all.api.radio-browser.info"


async def test_host_lookup_closes_the_resolver(
    responses: aioresponses, radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test the DNS resolver is closed after a lookup."""
    responses.get(f"{API_URL}/test", payload={})
    radios._host = None

    await radios._request("test")

    dns_resolver.return_value.__aexit__.assert_awaited_once()


@pytest.mark.usefixtures("retry_sleep")
async def test_host_lookup_cut_short_closes_the_resolver(
    radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test the DNS resolver is closed when the timeout cuts a lookup short."""

    async def unanswered_lookup(*_args: object) -> None:
        await asyncio.Event().wait()

    dns_resolver.return_value.query_dns.side_effect = unanswered_lookup
    radios._host = None
    radios.request_timeout = 0.01

    with pytest.raises(RadioBrowserConnectionTimeoutError):
        await radios._request("test")

    # One lookup per attempt, and every one of them closed its resolver.
    assert dns_resolver.return_value.__aexit__.await_count == 5


@pytest.mark.usefixtures("retry_sleep")
async def test_host_lookup_timeout(
    radios: RadioBrowser, dns_resolver: MagicMock
) -> None:
    """Test a DNS lookup that never answers runs into the request timeout."""

    async def unanswered_lookup(*_args: object) -> None:
        await asyncio.Event().wait()

    dns_resolver.return_value.query_dns.side_effect = unanswered_lookup
    radios._host = None
    radios.request_timeout = 0.01

    with pytest.raises(RadioBrowserConnectionTimeoutError):
        await radios._request("test")

    assert dns_resolver.return_value.query_dns.await_count == 5
    assert radios._host is None


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


async def test_request_after_close(responses: aioresponses) -> None:
    """Test a client can still be used after closing its own session."""
    responses.get(f"{API_URL}/test", status=200, payload={}, repeat=True)

    radios = RadioBrowser(user_agent="PythonRadios/Tests")
    await radios._request("test")
    first_session = radios.session
    await radios.close()

    assert await radios._request("test") == "{}"
    assert first_session is not None
    assert first_session.closed
    assert radios.session is not first_session

    await radios.close()


async def test_request_leaves_params_untouched(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test sending booleans does not rewrite the caller's params."""
    responses.get(f"{API_URL}/test?reverse=false", status=200, payload={})
    params = {"reverse": False}

    await radios._request("test", params=params)

    assert params == {"reverse": False}


async def test_close_without_session() -> None:
    """Test closing a client that never made a request does nothing."""
    radios = RadioBrowser(user_agent="PythonRadios/Tests")

    await radios.close()

    assert radios.session is None


@pytest.mark.parametrize(
    "call",
    [
        lambda radios: radios.stats(),
        lambda radios: radios.checks(),
        lambda radios: radios.clicks(),
        lambda radios: radios.station_click(uuid="x"),
        lambda radios: radios.vote(uuid="x"),
        lambda radios: radios.countries(),
        lambda radios: radios.languages(),
        lambda radios: radios.tags(),
        lambda radios: radios.codecs(),
        lambda radios: radios.states(),
        lambda radios: radios.states(country_code="NL"),
        lambda radios: radios.stations(),
        lambda radios: radios.station(uuid="x"),
        lambda radios: radios.stations_by_uuid(uuids=["x"]),
        lambda radios: radios.stations_by_url(url="x"),
        lambda radios: radios.search(),
    ],
    ids=[
        "stats",
        "checks",
        "clicks",
        "station_click",
        "vote",
        "countries",
        "languages",
        "tags",
        "codecs",
        "states",
        "states by country",
        "stations",
        "station",
        "stations_by_uuid",
        "stations_by_url",
        "search",
    ],
)
@pytest.mark.parametrize(
    "body",
    ["{", "null", '{"unexpected": 1}', "[{}]", '[{"name": null}]', "[1]"],
    ids=["broken", "null", "object", "empty item", "null name", "number"],
)
async def test_unexpected_response(
    responses: aioresponses,
    radios: RadioBrowser,
    call: Callable[[RadioBrowser], Awaitable[object]],
    body: str,
) -> None:
    """Test a response that cannot be parsed raises a Radio Browser error."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/"),
        body=body,
        content_type="application/json",
        repeat=True,
    )

    with pytest.raises(RadioBrowserError, match="Unexpected response") as error:
        await call(radios)

    assert not isinstance(error.value, RadioBrowserConnectionError)
    assert error.value.__cause__ is not None


@pytest.mark.parametrize(
    "method",
    ["codecs", "countries", "languages", "states", "tags", "stations", "search"],
)
@pytest.mark.parametrize(
    "paging", [{"limit": -1}, {"offset": -1}], ids=["limit", "offset"]
)
async def test_negative_paging(
    responses: aioresponses, radios: RadioBrowser, method: str, paging: dict[str, int]
) -> None:
    """Test a negative limit or offset is refused before a request is sent."""
    with pytest.raises(ValueError, match="cannot be negative"):
        await getattr(radios, method)(**paging)

    assert not responses.requests

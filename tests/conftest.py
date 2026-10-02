"""Common fixtures and helpers for Radio Browser API tests."""

from collections.abc import AsyncGenerator, Generator
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from aioresponses import core as aioresponses_core
from pycares import (
    QUERY_CLASS_IN,
    QUERY_TYPE_SRV,
    DNSRecord,
    DNSResult,
    SRVRecordData,
)

from radios import RadioBrowser

AIOHTTP_REQUIRES_STREAM_WRITER = (
    "stream_writer" in signature(aiohttp.ClientResponse.__init__).parameters
)
AIOHTTP_STREAM_WRITER_STUB = SimpleNamespace(output_size=0)

API_URL = "https://example.com/json"


class AioresponsesClientResponse(aioresponses_core.ClientResponse):
    """Backwards-compatible ClientResponse for aioresponses."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize and provide a stream_writer for aiohttp 3.14+."""
        if AIOHTTP_REQUIRES_STREAM_WRITER:
            kwargs.setdefault("stream_writer", AIOHTTP_STREAM_WRITER_STUB)
        super().__init__(*args, **kwargs)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a fixture file by name."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def srv_result(*targets: str) -> DNSResult:
    """Build a DNS SRV lookup result pointing at the given hosts."""
    return DNSResult(
        answer=[
            DNSRecord(
                name="_api._tcp.radio-browser.info",
                type=QUERY_TYPE_SRV,
                record_class=QUERY_CLASS_IN,
                ttl=300,
                data=SRVRecordData(priority=1, weight=1, port=443, target=target),
            )
            for target in targets
        ],
        authority=[],
        additional=[],
    )


@pytest.fixture(autouse=True)
def responses() -> Generator[aioresponses, None, None]:
    """Yield an aioresponses instance that patches aiohttp client sessions.

    It is active in every test, also the ones that do not ask for it, so no
    test can reach the real API by accident: an unmocked request fails.
    """
    with aioresponses() as mocker:
        yield mocker


@pytest.fixture(scope="session", autouse=True)
def setup_aioresponses_aiohttp_compat() -> Generator[None, None, None]:
    """Patch aioresponses ClientResponse for aiohttp compatibility in tests."""
    if not AIOHTTP_REQUIRES_STREAM_WRITER:
        yield
        return

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(aioresponses_core, "ClientResponse", AioresponsesClientResponse)
    try:
        yield
    finally:
        monkeypatch.undo()


@pytest.fixture(autouse=True)
def dns_resolver() -> Generator[MagicMock, None, None]:
    """Answer the DNS SRV lookup for the API host with example.com.

    A failed request forgets the host and looks it up again on the retry, so
    without this, tests would end up resolving the real API servers.
    """
    resolver = MagicMock()
    resolver.return_value.query_dns = AsyncMock(return_value=srv_result("example.com"))
    # The resolver is used as an async context manager, which hands out itself.
    resolver.return_value.__aenter__.return_value = resolver.return_value
    with patch("radios.radio_browser.DNSResolver", resolver):
        yield resolver


@pytest.fixture(autouse=True)
def corrections(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Run every test without the corrections the library ships.

    Those change as station data gets fixed, and should never break a test
    about something else. A test that wants corrections adds them here.
    """
    test_corrections: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr("radios.radio_browser.CORRECTIONS", test_corrections)
    return test_corrections


@pytest.fixture
async def radios() -> AsyncGenerator[RadioBrowser, None]:
    """Yield a Radio Browser client that talks to example.com.

    Setting the host up front skips the DNS SRV lookup, which the tests that
    care about it exercise on their own.
    """
    async with aiohttp.ClientSession() as session:
        radio_browser = RadioBrowser(user_agent="PythonRadios/Tests", session=session)
        radio_browser._host = "example.com"
        yield radio_browser

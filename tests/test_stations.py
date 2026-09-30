"""Tests for retrieving stations with the Radio Browser API client."""

import re

from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import FilterBy, Order, RadioBrowser

from .conftest import API_URL, load_fixture

STATION_UUID = "6c95ccdb-ca0a-4c59-a660-96e56ef2dca9"


async def test_stations(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing stations."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations\?"),
        status=200,
        body=load_fixture("stations.json"),
    )

    assert await radios.stations() == snapshot


async def test_stations_params(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test listing stations sends the paging and ordering parameters."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/stations\?"), payload=[])

    await radios.stations(
        hide_broken=True, limit=10, offset=20, order=Order.VOTES, reverse=True
    )

    ((_, url),) = responses.requests
    assert url.query == {
        "hidebroken": "true",
        "limit": "10",
        "offset": "20",
        "order": "votes",
        "reverse": "true",
    }


async def test_stations_filter_by(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test filter_by and filter_term end up in the request path."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/bycountrycodeexact/NL\?"),
        payload=[],
    )

    stations = await radios.stations(
        filter_by=FilterBy.COUNTRY_CODE_EXACT, filter_term="NL"
    )

    assert stations == []


async def test_stations_filter_by_without_term(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test filter_by without a term only adds the filter to the path."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/bycodec\?"),
        payload=[],
    )

    assert await radios.stations(filter_by=FilterBy.CODEC) == []


async def test_station(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test getting a single station by its UUID."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/byuuid/{STATION_UUID}\?"),
        status=200,
        body=load_fixture("stations.json"),
    )

    station = await radios.station(uuid=STATION_UUID)

    assert station == snapshot
    ((_, url),) = responses.requests
    assert url.query["limit"] == "1"


async def test_station_not_found(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test getting an unknown station returns None."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/byuuid/{STATION_UUID}\?"),
        payload=[],
    )

    assert await radios.station(uuid=STATION_UUID) is None


async def test_station_click(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test registering a click on a station."""
    responses.get(
        f"{API_URL}/url/{STATION_UUID}",
        payload={"ok": True, "message": "retrieved station url"},
    )

    await radios.station_click(uuid=STATION_UUID)

    assert len(responses.requests) == 1

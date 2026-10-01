"""Tests for retrieving stations with the Radio Browser API client."""

import re

import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import FilterBy, Order, RadioBrowser

from .conftest import API_URL, load_fixture

# What the API accepts, written out on purpose instead of importing the
# library's own constant, so a mistake there fails here.
SUPPORTED_STATION_ORDERS = set(Order) - {Order.CODE, Order.STATION_COUNT}

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


@pytest.mark.parametrize(
    ("filter_term", "path"),
    [
        ("#original", "/json/stations/bytagexact/%23original"),
        ("AC/DC", "/json/stations/bytagexact/AC%2FDC"),
        ("r&b", "/json/stations/bytagexact/r%26b"),
        ("80s 90s", "/json/stations/bytagexact/80s%2090s"),
    ],
)
async def test_stations_filter_term_is_escaped(
    responses: aioresponses, radios: RadioBrowser, filter_term: str, path: str
) -> None:
    """Test a filter term cannot change the URL it is part of."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/bytagexact/"), payload=[]
    )

    await radios.stations(filter_by=FilterBy.TAG_EXACT, filter_term=filter_term)

    ((_, url),) = responses.requests
    assert url.raw_path == path
    assert url.query["limit"] == "100000"


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
        status=200,
        body=load_fixture("station_click.json"),
    )

    url = await radios.station_click(uuid=STATION_UUID)

    assert url == (
        "http://playerservices.streamtheworld.com/api/livestream-redirect/TLPSTR09.mp3"
    )


async def test_station_click_uuid_is_escaped(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a station UUID cannot change the URL it is part of."""
    responses.get(
        f"{API_URL}/url/..%2Fstats", status=200, body=load_fixture("station_click.json")
    )

    await radios.station_click(uuid="../stats")

    ((_, url),) = responses.requests
    assert url.raw_path == "/json/url/..%2Fstats"


@pytest.mark.parametrize("method", ["stations", "search"])
@pytest.mark.parametrize("order", sorted(SUPPORTED_STATION_ORDERS))
async def test_station_orders(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test station lists send the orders the API can sort them by."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/"), payload=[])

    await getattr(radios, method)(order=order)

    ((_, url),) = responses.requests
    assert url.query["order"] == order.value


@pytest.mark.parametrize("method", ["stations", "search"])
@pytest.mark.parametrize("order", sorted(set(Order) - SUPPORTED_STATION_ORDERS))
async def test_station_orders_unsupported(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test station lists refuse the orders the API silently ignores."""
    with pytest.raises(ValueError, match=f"Order.{order.name}"):
        await getattr(radios, method)(order=order)

    assert not responses.requests

"""Tests for retrieving stations with the Radio Browser API client."""

import re

import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import (
    FilterBy,
    Order,
    RadioBrowser,
    RadioBrowserError,
    RadioBrowserValidationError,
)

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
    """Test filter_by without a term is refused, the API has no such path."""
    with pytest.raises(
        RadioBrowserValidationError, match="filter_by requires a filter_term"
    ):
        await radios.stations(filter_by=FilterBy.CODEC)

    assert not responses.requests


@pytest.mark.parametrize(
    ("filter_term", "path"),
    [
        ("#original", "/json/stations/bynameexact/%23original"),
        ("AC/DC", "/json/stations/bynameexact/AC%2FDC"),
        ("r&b", "/json/stations/bynameexact/r%26b"),
        ("80s 90s", "/json/stations/bynameexact/80s%2090s"),
    ],
)
async def test_stations_filter_term_is_escaped(
    responses: aioresponses, radios: RadioBrowser, filter_term: str, path: str
) -> None:
    """Test a filter term cannot change the URL it is part of."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/bynameexact/"), payload=[]
    )

    await radios.stations(filter_by=FilterBy.NAME_EXACT, filter_term=filter_term)

    ((_, url),) = responses.requests
    assert url.raw_path == path
    assert url.query["limit"] == "100000"


@pytest.mark.parametrize(
    ("filter_by", "path"),
    [
        (FilterBy.TAG, "/json/stations/bytag/jazz"),
        (FilterBy.TAG_EXACT, "/json/stations/bytagexact/jazz"),
        (FilterBy.LANGUAGE, "/json/stations/bylanguage/jazz"),
        (FilterBy.LANGUAGE_EXACT, "/json/stations/bylanguageexact/jazz"),
        (FilterBy.NAME_EXACT, "/json/stations/bynameexact/Jazz"),
        (FilterBy.STATE, "/json/stations/bystate/Jazz"),
    ],
)
async def test_stations_filter_term_case(
    responses: aioresponses, radios: RadioBrowser, filter_by: FilterBy, path: str
) -> None:
    """Test tag and language terms are lowercased, the API matches on that."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/stations/"), payload=[])

    await radios.stations(filter_by=filter_by, filter_term="Jazz")

    ((_, url),) = responses.requests
    assert url.raw_path == path


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


async def test_stations_by_uuid(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test getting several stations by their UUID in one request."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/byuuid\?"),
        status=200,
        body=load_fixture("stations.json"),
    )

    stations = await radios.stations_by_uuid(
        uuids=[STATION_UUID, "d1a54d2e-623e-4970-ab11-35f7b56c5ec3"]
    )

    assert stations == snapshot
    ((_, url),) = responses.requests
    assert url.query == {
        "uuids": f"{STATION_UUID},d1a54d2e-623e-4970-ab11-35f7b56c5ec3"
    }


async def test_stations_by_uuid_without_uuids(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test asking for no stations does not send a request."""
    assert await radios.stations_by_uuid(uuids=[]) == []
    assert not responses.requests


async def test_stations_by_url(responses: aioresponses, radios: RadioBrowser) -> None:
    """Test getting the stations behind a stream URL."""
    stream_url = (
        "http://playerservices.streamtheworld.com/api/livestream-redirect/TLPSTR09.mp3"
    )
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/byurl\?"),
        status=200,
        body=load_fixture("stations.json"),
    )

    stations = await radios.stations_by_url(url=stream_url)

    # Several stations can share a stream, so none of them may be dropped.
    assert [station.uuid for station in stations] == [
        STATION_UUID,
        "d1a54d2e-623e-4970-ab11-35f7b56c5ec3",
        "f592bcd7-c052-11e9-8502-52543be04c81",
    ]
    ((_, url),) = responses.requests
    assert url.query == {"url": stream_url}


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


@pytest.mark.parametrize("ok", [False, "false"])
async def test_station_click_not_registered(
    responses: aioresponses, radios: RadioBrowser, ok: object
) -> None:
    """Test a click the API does not register raises an error with its message."""
    responses.get(
        f"{API_URL}/url/{STATION_UUID}",
        payload={"ok": ok, "message": "station not found"},
    )

    with pytest.raises(RadioBrowserError, match="did not register the click"):
        await radios.station_click(uuid=STATION_UUID)


async def test_station_click_ok_as_string(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a click with "ok" as the string the documentation shows is fine."""
    responses.get(
        f"{API_URL}/url/{STATION_UUID}",
        payload={"ok": "true", "message": "retrieved station url", "url": "x"},
    )

    assert await radios.station_click(uuid=STATION_UUID) == "x"


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
    with pytest.raises(RadioBrowserValidationError, match="at 'order'"):
        await getattr(radios, method)(order=order)

    assert not responses.requests


@pytest.mark.parametrize("ok", [True, "true"])
async def test_vote(responses: aioresponses, radios: RadioBrowser, ok: object) -> None:
    """Test voting for a station."""
    responses.get(
        f"{API_URL}/vote/{STATION_UUID}",
        payload={"ok": ok, "message": "voted for station successfully"},
    )

    await radios.vote(uuid=STATION_UUID)

    assert len(responses.requests) == 1


@pytest.mark.parametrize("ok", [False, "false"])
async def test_vote_not_accepted(
    responses: aioresponses, radios: RadioBrowser, ok: object
) -> None:
    """Test a vote the API does not accept raises an error with its message."""
    responses.get(
        f"{API_URL}/vote/{STATION_UUID}",
        payload={"ok": ok, "message": "you are voting for the same station too often"},
    )

    with pytest.raises(RadioBrowserError, match="voting for the same station too"):
        await radios.vote(uuid=STATION_UUID)


async def test_vote_uuid_is_escaped(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a station UUID cannot change the URL it is part of."""
    responses.get(f"{API_URL}/vote/..%2Fstats", payload={"ok": True})

    await radios.vote(uuid="../stats")

    ((_, url),) = responses.requests
    assert url.raw_path == "/json/vote/..%2Fstats"

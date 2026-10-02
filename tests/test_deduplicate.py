"""Tests for returning one station per stream in lists."""

import re
from typing import Any

import orjson
import pytest
from aioresponses import aioresponses

from radios import RadioBrowser, Station
from radios.radio_browser import stream_key, without_duplicates

from .conftest import API_URL, load_fixture

STATIONS_URL = re.compile(rf"^{re.escape(API_URL)}/stations(\?|$)")
SEARCH_URL = re.compile(rf"^{re.escape(API_URL)}/stations/search")


def stations_with_duplicates() -> list[dict[str, Any]]:
    """Return the stations fixture, with two extra copies of the first stream."""
    stations = orjson.loads(load_fixture("stations.json"))
    original = stations[0]
    stations.append(
        original
        | {
            "stationuuid": "00000000-0000-4000-8000-000000000001",
            "url": original["url"].replace("http://", "https://") + "/",
            "votes": original["votes"] + 1,
        }
    )
    stations.append(
        original | {"stationuuid": "00000000-0000-4000-8000-000000000002", "votes": 0}
    )
    return stations


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("http://example.com/live", "https://example.com/live"),
        ("https://EXAMPLE.com/live", "https://example.com/live"),
        ("https://example.com/live/", "https://example.com/live"),
        ("http://example.com:8000/;", "http://example.com:8000"),
        (" https://example.com/live ", "https://example.com/live"),
    ],
)
def test_stream_key_same_stream(first: str, second: str) -> None:
    """Test ways to write the same stream URL get the same key."""
    assert stream_key(first) == stream_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://example.com/Live", "https://example.com/live"),
        ("https://example.com/live?id=1", "https://example.com/live?id=2"),
        ("https://example.com:8000/live", "https://example.com:8001/live"),
    ],
)
def test_stream_key_other_stream(first: str, second: str) -> None:
    """Test stream URLs that point to other streams get other keys."""
    assert stream_key(first) != stream_key(second)


def test_without_duplicates() -> None:
    """Test the most voted station stays, in the place of the first copy."""
    stations = [Station.from_dict(station) for station in stations_with_duplicates()]

    unique = without_duplicates(stations)

    assert [station.uuid for station in unique] == [
        "00000000-0000-4000-8000-000000000001",
        stations[1].uuid,
        stations[2].uuid,
    ]


def test_without_duplicates_ties_on_clicks() -> None:
    """Test clicks decide between copies with as many votes."""
    first, second = (
        Station.from_dict(station) for station in stations_with_duplicates()[:2]
    )
    first.url = second.url
    first.votes = second.votes
    first.click_count = second.click_count - 1

    assert without_duplicates([first, second]) == [second]


def test_without_duplicates_keeps_stations_without_url() -> None:
    """Test stations without a stream URL are not taken for duplicates."""
    first, second = (
        Station.from_dict(station) for station in stations_with_duplicates()[:2]
    )
    first.url = second.url = ""

    assert without_duplicates([first, second]) == [first, second]


@pytest.mark.parametrize(
    ("method", "url"),
    [("stations", STATIONS_URL), ("search", SEARCH_URL)],
)
async def test_lists_without_duplicates(
    responses: aioresponses,
    radios: RadioBrowser,
    method: str,
    url: re.Pattern[str],
) -> None:
    """Test lists of stations return one station per stream."""
    responses.get(url, status=200, body=orjson.dumps(stations_with_duplicates()))

    stations = await getattr(radios, method)()

    assert len(stations) == 3
    assert stations[0].uuid == "00000000-0000-4000-8000-000000000001"


async def test_deduplicate_can_be_turned_off(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a client without deduplication returns every station."""
    responses.get(
        STATIONS_URL, status=200, body=orjson.dumps(stations_with_duplicates())
    )
    radios.deduplicate = False

    assert len(await radios.stations()) == 5


@pytest.mark.parametrize(
    ("method", "arguments", "url"),
    [
        (
            "stations_by_uuid",
            {"uuids": ["6c95ccdb-ca0a-4c59-a660-96e56ef2dca9"]},
            re.compile(rf"^{re.escape(API_URL)}/stations/byuuid"),
        ),
        (
            "stations_by_url",
            {"url": "https://example.com"},
            re.compile(rf"^{re.escape(API_URL)}/stations/byurl"),
        ),
    ],
)
async def test_lookups_keep_duplicates(
    responses: aioresponses,
    radios: RadioBrowser,
    method: str,
    arguments: dict[str, Any],
    url: re.Pattern[str],
) -> None:
    """Test looking stations up returns every one, so saved stations are found."""
    responses.get(url, status=200, body=orjson.dumps(stations_with_duplicates()))

    assert len(await getattr(radios, method)(**arguments)) == 5


async def test_duplicates_after_corrections(
    responses: aioresponses,
    radios: RadioBrowser,
    corrections: dict[str, dict[str, Any]],
) -> None:
    """Test a corrected stream URL counts when looking for duplicates."""
    stations = orjson.loads(load_fixture("stations.json"))
    corrections[stations[1]["stationuuid"]] = {
        "stationuuid": stations[1]["stationuuid"],
        "reason": "Moved to the stream of the first station",
        "url": stations[0]["url"],
    }
    responses.get(STATIONS_URL, status=200, body=load_fixture("stations.json"))

    assert len(await radios.stations()) == 2

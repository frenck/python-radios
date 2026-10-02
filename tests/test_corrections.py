"""Tests for the corrections the library ships for the station data."""

import re
from pathlib import Path
from typing import Any

import orjson
import pytest
from aioresponses import aioresponses
from probatio import Invalid

from radios import RadioBrowser
from radios.corrections import (
    CORRECTIONS_PATH,
    FILE_SCHEMA,
    apply_corrections,
    correction_files,
    json_schema,
    load_corrections,
)

from .conftest import API_URL, load_fixture

# The first station in the stations fixture.
STATION_UUID = "6c95ccdb-ca0a-4c59-a660-96e56ef2dca9"
STATIONS_URL = re.compile(rf"^{re.escape(API_URL)}/stations(\?|$)")
CORRECTED_URL = "https://example.com/538.mp3"

SHIPPED_FILES = correction_files()


def test_corrections_are_shipped() -> None:
    """Test the library ships correction files, and loads them."""
    assert SHIPPED_FILES
    assert load_corrections()


@pytest.mark.parametrize(
    "path",
    SHIPPED_FILES,
    ids=[path.parent.name + "/" + path.name for path in SHIPPED_FILES],
)
def test_shipped_file_is_valid(path: Path) -> None:
    """Test a shipped correction file follows the schema and naming rules."""
    FILE_SCHEMA(orjson.loads(path.read_bytes()))

    # The folder is the country, the file is named after a broadcaster or topic.
    assert re.fullmatch(r"[a-z]{2}", path.parent.name)
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*\.json", path.name)


def test_shipped_stations_are_corrected_once() -> None:
    """Test no station has corrections in more than one place."""
    uuids = [
        correction["stationuuid"]
        for path in SHIPPED_FILES
        for correction in orjson.loads(path.read_bytes())["corrections"]
    ]

    assert len(uuids) == len(set(uuids))


def test_json_schema_is_up_to_date() -> None:
    """Test schema.json matches the schema the files are validated with."""
    stored = orjson.loads((CORRECTIONS_PATH / "schema.json").read_bytes())

    assert stored == json_schema(), (
        "schema.json is out of date, regenerate it with: poetry run python -c "
        '"import orjson; from radios.corrections import json_schema; '
        "open('src/radios/corrections/schema.json', 'wb').write("
        'orjson.dumps(json_schema(), option=orjson.OPT_INDENT_2))"'
    )


@pytest.mark.parametrize(
    "correction",
    [
        {"stationuuid": STATION_UUID, "reason": "No changes"},
        {"stationuuid": STATION_UUID, "reason": "", "name": "538"},
        {"stationuuid": "538", "reason": "Not a UUID", "name": "538"},
        {"stationuuid": STATION_UUID, "reason": "Unknown field", "votes": 1},
        {"stationuuid": STATION_UUID, "reason": "Not a URL", "url": "538"},
        {"stationuuid": STATION_UUID, "reason": "Lowercase", "countrycode": "nl"},
        {"stationuuid": STATION_UUID, "reason": "Off the map", "geo_lat": 91},
        {"stationuuid": STATION_UUID, "reason": "Both", "delete": True, "name": "538"},
        {"stationuuid": STATION_UUID, "reason": "Not deleted", "delete": False},
    ],
    ids=[
        "no-changes",
        "empty-reason",
        "uuid",
        "unknown-field",
        "url",
        "countrycode",
        "geo_lat",
        "delete-and-change",
        "delete-false",
    ],
)
def test_schema_refuses_invalid_corrections(correction: dict[str, Any]) -> None:
    """Test the schema refuses a correction that is not valid."""
    with pytest.raises(Invalid):
        FILE_SCHEMA({"$schema": "../schema.json", "corrections": [correction]})


def test_load_corrections(tmp_path: Path) -> None:
    """Test corrections load from every country folder, by station UUID."""
    (tmp_path / "nl").mkdir()
    (tmp_path / "nl" / "npo.json").write_bytes(
        orjson.dumps(
            {
                "$schema": "../schema.json",
                "corrections": [
                    {
                        "stationuuid": STATION_UUID,
                        "reason": "Moved",
                        "url": CORRECTED_URL,
                    }
                ],
            }
        )
    )
    # Files outside a country folder, like the schema itself, are not loaded.
    (tmp_path / "schema.json").write_bytes(b"{}")

    assert load_corrections(tmp_path) == {
        STATION_UUID: {
            "stationuuid": STATION_UUID,
            "reason": "Moved",
            "url": CORRECTED_URL,
        }
    }


def test_apply_corrections() -> None:
    """Test a correction changes or deletes a station, and leaves the rest alone."""
    stations = [
        {
            "stationuuid": "a",
            "name": "A",
            "url": "https://a",
            "url_resolved": "https://a",
        },
        {
            "stationuuid": "b",
            "name": "B",
            "url": "https://b",
            "url_resolved": "https://b",
        },
        {
            "stationuuid": "c",
            "name": "C",
            "url": "https://c",
            "url_resolved": "https://c",
        },
    ]
    corrections = {
        "a": {"stationuuid": "a", "reason": "Renamed", "name": "Aa"},
        "b": {"stationuuid": "b", "reason": "Duplicate", "delete": True},
        "c": {"stationuuid": "c", "reason": "Moved", "url": "https://cc"},
    }

    assert apply_corrections(stations, corrections) == [
        {
            "stationuuid": "a",
            "name": "Aa",
            "url": "https://a",
            "url_resolved": "https://a",
        },
        {
            "stationuuid": "c",
            "name": "C",
            "url": "https://cc",
            "url_resolved": "https://cc",
        },
    ]
    # The stations from the API are not changed in place.
    assert stations[0]["name"] == "A"


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("stations", STATIONS_URL),
        ("search", re.compile(rf"^{re.escape(API_URL)}/stations/search")),
        ("stations_by_uuid", re.compile(rf"^{re.escape(API_URL)}/stations/byuuid")),
        ("stations_by_url", re.compile(rf"^{re.escape(API_URL)}/stations/byurl")),
    ],
)
async def test_station_methods_apply_corrections(
    responses: aioresponses,
    radios: RadioBrowser,
    corrections: dict[str, dict[str, Any]],
    method: str,
    url: str | re.Pattern[str],
) -> None:
    """Test every method that returns stations applies the corrections."""
    corrections[STATION_UUID] = {
        "stationuuid": STATION_UUID,
        "reason": "Moved",
        "url": CORRECTED_URL,
    }
    responses.get(url, status=200, body=load_fixture("stations.json"))
    arguments = {
        "stations_by_uuid": {"uuids": [STATION_UUID]},
        "stations_by_url": {"url": "https://example.com"},
    }.get(method, {})

    stations = await getattr(radios, method)(**arguments)

    assert stations[0].uuid == STATION_UUID
    assert stations[0].url == CORRECTED_URL
    assert stations[0].url_resolved == CORRECTED_URL


async def test_deleted_station_is_left_out(
    responses: aioresponses,
    radios: RadioBrowser,
    corrections: dict[str, dict[str, Any]],
) -> None:
    """Test a deleted station is left out of the results."""
    corrections[STATION_UUID] = {
        "stationuuid": STATION_UUID,
        "reason": "Duplicate",
        "delete": True,
    }
    responses.get(STATIONS_URL, status=200, body=load_fixture("stations.json"))

    stations = await radios.stations()

    assert STATION_UUID not in {station.uuid for station in stations}
    assert len(stations) == 2


async def test_corrections_can_be_turned_off(
    responses: aioresponses,
    radios: RadioBrowser,
    corrections: dict[str, dict[str, Any]],
) -> None:
    """Test a client without corrections returns the stations as the API does."""
    corrections[STATION_UUID] = {
        "stationuuid": STATION_UUID,
        "reason": "Duplicate",
        "delete": True,
    }
    responses.get(STATIONS_URL, status=200, body=load_fixture("stations.json"))
    radios.corrections = False

    stations = await radios.stations()

    assert len(stations) == 3


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        (True, CORRECTED_URL),
        (
            False,
            "http://playerservices.streamtheworld.com/api/livestream-redirect/TLPSTR09.mp3",
        ),
    ],
)
async def test_station_click_returns_corrected_url(
    responses: aioresponses,
    radios: RadioBrowser,
    corrections: dict[str, dict[str, Any]],
    enabled: bool,
    expected: str,
) -> None:
    """Test a click returns the corrected stream URL, and still counts upstream."""
    corrections[STATION_UUID] = {
        "stationuuid": STATION_UUID,
        "reason": "Moved",
        "url": CORRECTED_URL,
    }
    responses.get(
        f"{API_URL}/url/{STATION_UUID}",
        status=200,
        body=load_fixture("station_click.json"),
    )
    radios.corrections = enabled

    assert await radios.station_click(uuid=STATION_UUID) == expected
    assert responses.requests

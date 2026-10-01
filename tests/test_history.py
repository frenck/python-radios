"""Tests for the check and click history of stations."""

import re

import orjson
import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import RadioBrowser, StationCheck

from .conftest import API_URL, load_fixture

STATION_UUID = "d1a54d2e-623e-4970-ab11-35f7b56c5ec3"


async def test_checks(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test getting the check history of a station."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/checks/{STATION_UUID}\?"),
        status=200,
        body=load_fixture("checks.json"),
    )

    assert await radios.checks(uuid=STATION_UUID) == snapshot


async def test_clicks(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test getting the clicks on a station."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/clicks/{STATION_UUID}\?"),
        status=200,
        body=load_fixture("clicks.json"),
    )

    assert await radios.clicks(uuid=STATION_UUID) == snapshot


@pytest.mark.parametrize(
    ("method", "after_param"),
    [("checks", "lastcheckuuid"), ("clicks", "lastclickuuid")],
)
async def test_history_params(
    responses: aioresponses, radios: RadioBrowser, method: str, after_param: str
) -> None:
    """Test the history of all stations sends the paging parameters."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}\?"), payload=[])

    await getattr(radios, method)(after="some-uuid", seconds=3600, limit=10)

    ((_, url),) = responses.requests
    assert url.raw_path == f"/json/{method}"
    assert url.query == {after_param: "some-uuid", "seconds": "3600", "limit": "10"}


@pytest.mark.parametrize("method", ["checks", "clicks"])
async def test_history_leaves_out_unset_params(
    responses: aioresponses, radios: RadioBrowser, method: str
) -> None:
    """Test unset history filters are not sent at all."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}\?"), payload=[])

    await getattr(radios, method)()

    ((_, url),) = responses.requests
    assert url.query == {"limit": "100000"}


@pytest.mark.parametrize("method", ["checks", "clicks"])
@pytest.mark.parametrize(
    "arguments", [{"limit": -1}, {"seconds": -1}], ids=["limit", "seconds"]
)
async def test_history_negative_arguments(
    responses: aioresponses,
    radios: RadioBrowser,
    method: str,
    arguments: dict[str, int],
) -> None:
    """Test a negative limit or seconds is refused before a request is sent."""
    with pytest.raises(ValueError, match="cannot be negative"):
        await getattr(radios, method)(**arguments)

    assert not responses.requests


def test_check_without_optional_fields() -> None:
    """Test a check with nulls where a stream reported little still loads."""
    check = orjson.loads(load_fixture("checks.json"))[1]
    check.update({"tags": None, "languagecodes": None, "name": None})

    station_check = StationCheck.from_dict(check)

    assert station_check.tags == []
    assert station_check.language_codes == []
    assert station_check.name is None
    assert station_check.country_code is None


def test_check_with_only_required_fields() -> None:
    """Test a check that only has the fields every check has still loads."""
    full = orjson.loads(load_fixture("checks.json"))[0]
    required = (
        "checkuuid",
        "stationuuid",
        "timestamp_iso8601",
        "ok",
        "source",
        "codec",
        "bitrate",
        "hls",
        "urlcache",
        "metainfo_overrides_database",
        "timing_ms",
        "ssl_error",
    )

    station_check = StationCheck.from_dict({key: full[key] for key in required})

    assert station_check.tags == []
    assert station_check.language_codes == []
    assert station_check.name is None
    assert station_check.country_code is None
    assert station_check.latitude is None
    assert station_check.public is None


@pytest.mark.parametrize("method", ["checks", "clicks"])
async def test_history_uuid_is_escaped(
    responses: aioresponses, radios: RadioBrowser, method: str
) -> None:
    """Test a station UUID cannot change the URL it is part of."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}/"), payload=[])

    await getattr(radios, method)(uuid="../stats")

    ((_, url),) = responses.requests
    assert url.raw_path == f"/json/{method}/..%2Fstats"

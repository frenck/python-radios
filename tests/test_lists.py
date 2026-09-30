"""Tests for the stats, countries, languages and tags endpoints."""

import re

from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import Order, RadioBrowser

from .conftest import API_URL, load_fixture


async def test_stats(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test getting the Radio Browser service stats."""
    responses.get(f"{API_URL}/stats", status=200, body=load_fixture("stats.json"))

    assert await radios.stats() == snapshot


async def test_countries(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing countries resolves their names and sorts by them."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        status=200,
        body=load_fixture("countrycodes.json"),
    )

    countries = await radios.countries()

    assert countries == snapshot
    # Kosovo is not in pycountry, and unknown codes keep their code as name.
    assert [country.name for country in countries] == [
        "Germany",
        "Kosovo",
        "Netherlands",
        "XX",
    ]


async def test_countries_keep_api_order(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test countries are only re-sorted when ordered by name."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        status=200,
        body=load_fixture("countrycodes.json"),
    )

    countries = await radios.countries(order=Order.STATION_COUNT)

    assert [country.code for country in countries] == ["XK", "NL", "DE", "XX"]
    ((_, url),) = responses.requests
    assert url.query["order"] == "stationcount"


async def test_languages(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing languages title-cases their names."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/languages\?"),
        status=200,
        body=load_fixture("languages.json"),
    )

    languages = await radios.languages()

    assert languages == snapshot
    assert [language.name for language in languages] == [
        "Dutch",
        "English",
        "#English",
    ]


async def test_tags(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing tags."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/tags\?"),
        status=200,
        body=load_fixture("tags.json"),
    )

    assert await radios.tags() == snapshot

"""Tests for the stats, countries, languages and tags endpoints."""

import re

import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion

from radios import Order, RadioBrowser

from .conftest import API_URL, load_fixture

# What the API accepts, written out on purpose instead of importing the
# library's own constant, so a mistake there fails here.
SUPPORTED_LIST_ORDERS = {Order.NAME, Order.STATION_COUNT}


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

    countries = await radios.countries(
        order=Order.STATION_COUNT, reverse=True, limit=10, offset=20
    )

    assert [country.code for country in countries] == ["XK", "NL", "DE", "XX"]
    # The API can sort by station count itself, so it also does the paging.
    ((_, url),) = responses.requests
    assert url.query == {
        "hidebroken": "false",
        "order": "stationcount",
        "limit": "10",
        "offset": "20",
        "reverse": "true",
    }


@pytest.mark.parametrize(
    ("reverse", "offset", "limit", "expected"),
    [
        (False, 0, 100000, ["Germany", "Kosovo", "Netherlands", "XX"]),
        (True, 0, 100000, ["XX", "Netherlands", "Kosovo", "Germany"]),
        (False, 1, 2, ["Kosovo", "Netherlands"]),
        (True, 1, 2, ["Netherlands", "Kosovo"]),
        (False, 3, 10, ["XX"]),
        (False, 10, 10, []),
    ],
)
async def test_countries_by_name(  # noqa: PLR0913
    responses: aioresponses,
    radios: RadioBrowser,
    reverse: bool,
    offset: int,
    limit: int,
    expected: list[str],
) -> None:
    """Test countries are sorted and paged by their name, not their code."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        status=200,
        body=load_fixture("countrycodes.json"),
    )

    countries = await radios.countries(reverse=reverse, offset=offset, limit=limit)

    assert [country.name for country in countries] == expected
    # The API would sort and page on the code, so the whole list is fetched.
    ((_, url),) = responses.requests
    assert url.query == {"hidebroken": "false", "order": "name"}


async def test_countries_by_name_ignores_accents(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test accented country names sort with their letter, not after Z."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        payload=[
            {"name": "ZW", "stationcount": 1},
            {"name": "AX", "stationcount": 1},
            {"name": "CI", "stationcount": 1},
            {"name": "CY", "stationcount": 1},
            {"name": "AF", "stationcount": 1},
        ],
    )

    countries = await radios.countries()

    assert [country.name for country in countries] == [
        "Afghanistan",
        "Åland Islands",
        "Côte d'Ivoire",
        "Cyprus",
        "Zimbabwe",
    ]


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


@pytest.mark.parametrize("method", ["countries", "languages", "tags"])
@pytest.mark.parametrize("order", sorted(SUPPORTED_LIST_ORDERS))
async def test_list_orders(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test lists send the orders the API can sort them by."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/"), payload=[])

    await getattr(radios, method)(order=order)

    ((_, url),) = responses.requests
    assert url.query["order"] == order.value


@pytest.mark.parametrize("method", ["countries", "languages", "tags"])
@pytest.mark.parametrize("order", sorted(set(Order) - SUPPORTED_LIST_ORDERS))
async def test_list_orders_unsupported(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test lists refuse orders the API answers with a server error."""
    with pytest.raises(ValueError, match=f"Order.{order.name}"):
        await getattr(radios, method)(order=order)

    assert not responses.requests

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


@pytest.mark.parametrize(
    ("reverse", "offset", "limit", "expected"),
    [
        (False, 0, 100000, ["XX", "XK", "NL", "DE"]),
        (True, 0, 100000, ["DE", "NL", "XK", "XX"]),
        (True, 1, 2, ["NL", "XK"]),
    ],
)
async def test_countries_by_station_count(  # noqa: PLR0913
    responses: aioresponses,
    radios: RadioBrowser,
    reverse: bool,
    offset: int,
    limit: int,
    expected: list[str],
) -> None:
    """Test countries are sorted and paged by their station count."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        status=200,
        body=load_fixture("countrycodes.json"),
    )

    countries = await radios.countries(
        order=Order.STATION_COUNT, reverse=reverse, offset=offset, limit=limit
    )

    assert [country.code for country in countries] == expected


async def test_countries_fetch_the_whole_list(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test countries are fetched in full, the client sorts and pages them."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"), payload=[])

    await radios.countries(
        hide_broken=True, order=Order.STATION_COUNT, reverse=True, limit=10, offset=5
    )

    ((_, url),) = responses.requests
    assert url.query == {"hidebroken": "true"}


async def test_countries_merge_lowercase_codes(
    responses: aioresponses, radios: RadioBrowser
) -> None:
    """Test a country listed again under a lowercase code is counted once."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        payload=[
            {"name": "DE", "stationcount": 6470},
            {"name": "NL", "stationcount": 1546},
            {"name": "de", "stationcount": 1},
        ],
    )

    countries = await radios.countries()

    assert [
        (country.code, country.name, country.station_count) for country in countries
    ] == [("DE", "Germany", 6471), ("NL", "Netherlands", 1546)]


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


@pytest.mark.parametrize("method", ["codecs", "languages", "states", "tags"])
async def test_list_params(
    responses: aioresponses, radios: RadioBrowser, method: str
) -> None:
    """Test languages and tags send every paging and ordering parameter."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}\?"), payload=[])

    await getattr(radios, method)(
        hide_broken=True,
        limit=10,
        offset=20,
        order=Order.STATION_COUNT,
        reverse=True,
    )

    ((_, url),) = responses.requests
    assert url.query == {
        "hidebroken": "true",
        "limit": "10",
        "offset": "20",
        "order": "stationcount",
        "reverse": "true",
    }


@pytest.mark.parametrize(
    ("method", "name", "path"),
    [
        ("codecs", "AAC", "/json/codecs/aac"),
        ("languages", "Dutch", "/json/languages/dutch"),
        ("tags", "R&B", "/json/tags/r%26b"),
        ("tags", "80s/90s", "/json/tags/80s%2F90s"),
    ],
)
async def test_list_name_filter(
    responses: aioresponses, radios: RadioBrowser, method: str, name: str, path: str
) -> None:
    """Test languages and tags are filtered by the API, on the lowercase name."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}/"), payload=[])

    await getattr(radios, method)(name=name)

    ((_, url),) = responses.requests
    assert url.raw_path == path


@pytest.mark.parametrize("method", ["codecs", "languages", "states", "tags"])
async def test_list_without_name_filter(
    responses: aioresponses, radios: RadioBrowser, method: str
) -> None:
    """Test languages and tags are not filtered when no name is given."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/{method}\?"), payload=[])

    await getattr(radios, method)(name="")

    ((_, url),) = responses.requests
    assert url.raw_path == f"/json/{method}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("land", ["Åland Islands", "Netherlands"]),
        ("ALAND", ["Åland Islands"]),
        ("kosovo", ["Kosovo"]),
        ("nowhere", []),
    ],
)
async def test_countries_name_filter(
    responses: aioresponses, radios: RadioBrowser, name: str, expected: list[str]
) -> None:
    """Test countries are filtered on their name, ignoring case and accents."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/countrycodes\?"),
        payload=[
            {"name": "NL", "stationcount": 1},
            {"name": "AX", "stationcount": 1},
            {"name": "XK", "stationcount": 1},
            {"name": "DE", "stationcount": 1},
        ],
    )

    countries = await radios.countries(name=name)

    assert [country.name for country in countries] == expected
    # The API only knows codes, so the filter is not sent along.
    ((_, url),) = responses.requests
    assert url.raw_path == "/json/countrycodes"


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


@pytest.mark.parametrize("method", ["codecs", "languages", "states", "tags"])
@pytest.mark.parametrize("order", sorted(SUPPORTED_LIST_ORDERS))
async def test_list_orders(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test lists send the orders the API can sort them by."""
    responses.get(re.compile(rf"^{re.escape(API_URL)}/"), payload=[])

    await getattr(radios, method)(order=order)

    ((_, url),) = responses.requests
    assert url.query["order"] == order.value


@pytest.mark.parametrize(
    "method", ["codecs", "countries", "languages", "states", "tags"]
)
@pytest.mark.parametrize("order", sorted(set(Order) - SUPPORTED_LIST_ORDERS))
async def test_list_orders_unsupported(
    responses: aioresponses, radios: RadioBrowser, method: str, order: Order
) -> None:
    """Test lists refuse orders the API answers with a server error."""
    with pytest.raises(ValueError, match=f"Order.{order.name}"):
        await getattr(radios, method)(order=order)

    assert not responses.requests


async def test_codecs(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing the codecs stations stream in."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/codecs\?"),
        status=200,
        body=load_fixture("codecs.json"),
    )

    assert await radios.codecs(order=Order.STATION_COUNT, reverse=True) == snapshot


async def test_states(
    responses: aioresponses, radios: RadioBrowser, snapshot: SnapshotAssertion
) -> None:
    """Test listing the states of a country, by its country code."""
    responses.get(
        f"{API_URL}/countries", status=200, body=load_fixture("countries.json")
    )
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/states/"),
        status=200,
        body=load_fixture("states.json"),
    )

    assert await radios.states(country_code="NL", name="utrecht") == snapshot


@pytest.mark.parametrize(
    ("country_code", "name", "path"),
    [
        (None, None, "/json/states"),
        (None, "Utrecht", "/json/states/Utrecht"),
        ("NL", None, "/json/states/The%20Netherlands/"),
        ("nl", "Utrecht", "/json/states/The%20Netherlands/Utrecht"),
        ("CI", "a/b", "/json/states/Coted%20Ivoire/a%2Fb"),
    ],
)
async def test_states_path(
    responses: aioresponses,
    radios: RadioBrowser,
    country_code: str | None,
    name: str | None,
    path: str,
) -> None:
    """Test the API name of the country and the name end up in the path."""
    responses.get(
        f"{API_URL}/countries", status=200, body=load_fixture("countries.json")
    )
    responses.get(re.compile(rf"^{re.escape(API_URL)}/states"), payload=[])

    await radios.states(country_code=country_code, name=name)

    (states_url,) = [url for _, url in responses.requests if "states" in url.path]
    assert states_url.raw_path == path


@pytest.mark.parametrize("country_code", ["ZZ", "XX"], ids=["missing", "nameless"])
async def test_states_unknown_country_code(
    responses: aioresponses, radios: RadioBrowser, country_code: str
) -> None:
    """Test an unknown country code has no states, without asking for them."""
    # The API really lists "XX" in its countries, with an empty name. Taking
    # that name as a filter would return the states of every country.
    responses.get(
        f"{API_URL}/countries", status=200, body=load_fixture("countries.json")
    )

    assert await radios.states(country_code=country_code) == []
    assert [url.path for _, url in responses.requests] == ["/json/countries"]

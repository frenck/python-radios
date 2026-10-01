"""Tests for the Radio Browser API models."""

import orjson
import pytest

from radios import Country, Language, Station, Tag

from .conftest import load_fixture


def _stations() -> list[Station]:
    """Load the station fixture as models."""
    return [
        Station.from_dict(station)
        for station in orjson.loads(load_fixture("stations.json"))
    ]


def test_station_country() -> None:
    """Test a station resolves its country code to a country name."""
    _, classic_vinyl, _ = _stations()

    assert classic_vinyl.country_code == "US"
    assert classic_vinyl.country == "United States"


def test_station_without_country() -> None:
    """Test a station without a country code has no country."""
    station, _, _ = _stations()

    assert station.country_code == ""
    assert station.country is None


def test_station_comma_separated_fields() -> None:
    """Test comma separated fields are split into lists."""
    _, classic_vinyl, _ = _stations()

    assert classic_vinyl.language == ["english"]
    assert classic_vinyl.language_codes == ["en"]
    assert classic_vinyl.tags[:3] == ["1930", "1940", "1950"]


def test_station_empty_comma_separated_fields() -> None:
    """Test empty comma separated fields become empty lists."""
    station, _, rey_fm = _stations()

    assert station.tags == []
    assert rey_fm.language == []
    assert rey_fm.language_codes == []


def test_station_comma_separated_fields_serialize() -> None:
    """Test comma separated fields are joined again when serialized."""
    _, classic_vinyl, _ = _stations()

    serialized = classic_vinyl.to_dict()

    assert serialized["tags"] == ",".join(classic_vinyl.tags)
    assert serialized["language"] == "english"


def test_station_count_is_an_integer() -> None:
    """Test station counts are integers, like the API sends them."""
    country = Country.from_dict({"code": "NL", "name": "NL", "stationcount": 1545})
    language = Language.from_dict(
        {"iso_639": "nl", "name": "dutch", "stationcount": 926}
    )
    tag = Tag.from_dict({"name": "pop", "stationcount": 6337})

    assert country.station_count == 1545
    assert language.station_count == 926
    assert tag.station_count == 6337


def test_country_favicon() -> None:
    """Test a country links to its flag."""
    country = Country(code="NL", name="Netherlands", station_count=1545)

    assert country.favicon == "https://flagcdn.com/256x192/nl.png"


def test_language_favicon() -> None:
    """Test a language with a code links to a flag."""
    language = Language(code="nl", name="Dutch", station_count=926)

    assert language.favicon == "https://flagcdn.com/256x192/nl.png"


@pytest.mark.parametrize(
    ("code", "flag"),
    [
        ("en", "gb"),
        ("ja", "jp"),
        ("sv", "se"),
        ("sr", "rs"),
        ("EN", "gb"),
    ],
)
def test_language_favicon_is_a_country_flag(code: str, flag: str) -> None:
    """Test a language links to its country, not a country sharing its code."""
    language = Language(code=code, name="Name", station_count=1)

    assert language.favicon == f"https://flagcdn.com/256x192/{flag}.png"


def test_language_without_single_country_has_no_favicon() -> None:
    """Test a language spoken across many countries has no flag."""
    # "ar" is the country code of Argentina, which is not where Arabic is from.
    language = Language(code="ar", name="Arabic", station_count=570)

    assert language.favicon is None


def test_language_without_code_has_no_favicon() -> None:
    """Test a language without a code has no flag."""
    language = Language(code=None, name="#English", station_count=3)

    assert language.favicon is None

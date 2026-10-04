"""Tests for the country names the library ships."""

import pycountry
import pytest

from radios.country_names import COUNTRY_NAMES
from radios.models import country_name


def test_every_country_has_a_name() -> None:
    """Test every ISO 3166-1 country, and Kosovo, has a name, and nothing else."""
    iso_codes = {country.alpha_2 for country in pycountry.countries}

    assert set(COUNTRY_NAMES) == iso_codes | {"XK"}
    assert all(COUNTRY_NAMES.values())


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("NL", "Netherlands"),
        ("KR", "South Korea"),
        ("CI", "Côte d'Ivoire"),
        ("HK", "Hong Kong"),
        ("CD", "Congo (DRC)"),
        ("XK", "Kosovo"),
    ],
)
def test_country_name(code: str, name: str) -> None:
    """Test a country code resolves to its common English name."""
    assert country_name(code) == name
    assert country_name(code.lower()) == name


def test_unknown_country_name() -> None:
    """Test an unknown country code has no name."""
    assert country_name("ZZ") is None

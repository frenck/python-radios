"""Models for the Radio Browser API."""

# pylint: disable=too-few-public-methods
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pycountry
from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializationStrategy

from .const import LANGUAGE_FLAGS


def country_name(country_code: str) -> str | None:
    """Return the name of a country by its ISO 3166-1 alpha-2 code.

    Args:
    ----
        country_code: Two letter country code, for example `NL`.

    Returns:
    -------
        The country name, or None if the code is unknown.

    """
    # Kosovo has a user-assigned code that is not part of ISO 3166-1, so
    # pycountry does not know it. https://github.com/frenck/python-radios/issues/19
    if country_code.upper() == "XK":
        return "Kosovo"

    if country := pycountry.countries.get(alpha_2=country_code):
        return country.name  # type: ignore[return-value]

    return None


class CommaSeparatedString(SerializationStrategy):
    """String serialization strategy to handle comma separated strings."""

    def serialize(self, value: list[str]) -> str:
        """Serialize a list of strings to a comma separated value."""
        return ",".join(value)

    def deserialize(self, value: str | None) -> list[str]:
        """Deserialize a comma separated value to a list of strings."""
        # Check results send null instead of an empty string.
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
# pylint: disable=too-many-instance-attributes
class Stats(DataClassORJSONMixin):
    """Object holding the Radio Browser stats."""

    supported_version: int
    software_version: AwesomeVersion
    status: str
    stations: int
    stations_broken: int
    tags: int
    clicks_last_hour: int
    clicks_last_day: int
    languages: int
    countries: int


@dataclass
# pylint: disable=too-many-instance-attributes
class Station(DataClassORJSONMixin):
    """Object information for a station from the Radio Browser."""

    bitrate: int
    change_uuid: str = field(metadata=field_options(alias="changeuuid"))
    click_count: int = field(metadata=field_options(alias="clickcount"))
    click_timestamp: datetime | None = field(
        metadata=field_options(alias="clicktimestamp_iso8601")
    )
    click_trend: int = field(metadata=field_options(alias="clicktrend"))
    codec: str
    country_code: str = field(metadata=field_options(alias="countrycode"))
    favicon: str
    latitude: float | None = field(metadata=field_options(alias="geo_lat"))
    longitude: float | None = field(metadata=field_options(alias="geo_long"))
    hls: bool
    homepage: str
    iso_3166_2: str | None
    language: list[str] = field(
        metadata=field_options(serialization_strategy=CommaSeparatedString())
    )
    language_codes: list[str] = field(
        metadata=field_options(
            alias="languagecodes", serialization_strategy=CommaSeparatedString()
        )
    )
    last_change_time: datetime | None = field(
        metadata=field_options(alias="lastchangetime_iso8601")
    )
    last_check_ok: bool = field(metadata=field_options(alias="lastcheckok"))
    last_check_ok_time: datetime | None = field(
        metadata=field_options(alias="lastcheckoktime_iso8601")
    )
    last_check_time: datetime | None = field(
        metadata=field_options(alias="lastchecktime_iso8601")
    )
    last_local_check_time: datetime | None = field(
        metadata=field_options(alias="lastlocalchecktime_iso8601")
    )
    name: str
    ssl_error: int | None
    state: str
    uuid: str = field(metadata=field_options(alias="stationuuid"))
    tags: list[str] = field(
        metadata=field_options(serialization_strategy=CommaSeparatedString())
    )
    url_resolved: str
    url: str
    votes: int

    # The API leaves these out of some responses, so they get a default.
    # Fields with a default have to come after the ones without, hence they
    # live here.
    has_extended_info: bool = False
    # Distance in meters from the location of a geo search, only set on the
    # results of one.
    distance: float | None = field(
        default=None, metadata=field_options(alias="geo_distance")
    )

    @property
    def country(self) -> str | None:
        """Return country name of this station.

        Returns
        -------
            Country name or None if no country code is set.

        """
        return country_name(self.country_code)


@dataclass
# pylint: disable=too-many-instance-attributes
class StationCheck(DataClassORJSONMixin):
    """Object information for a check of a station by the Radio Browser.

    The Radio Browser servers check every station regularly: is the stream
    online, and what does it send. Only the fields that are always there are
    required, the rest depends on what the stream reports.
    """

    uuid: str = field(metadata=field_options(alias="checkuuid"))
    station_uuid: str = field(metadata=field_options(alias="stationuuid"))
    timestamp: datetime | None = field(
        metadata=field_options(alias="timestamp_iso8601")
    )
    ok: bool
    source: str
    codec: str
    bitrate: int
    hls: bool
    url: str = field(metadata=field_options(alias="urlcache"))
    metainfo_overrides_database: bool
    timing_ms: int | None
    ssl_error: int | None

    name: str | None = None
    description: str | None = None
    tags: list[str] = field(
        default_factory=list,
        metadata=field_options(serialization_strategy=CommaSeparatedString()),
    )
    language_codes: list[str] = field(
        default_factory=list,
        metadata=field_options(
            alias="languagecodes", serialization_strategy=CommaSeparatedString()
        ),
    )
    country_code: str | None = field(
        default=None, metadata=field_options(alias="countrycode")
    )
    country_subdivision_code: str | None = field(
        default=None, metadata=field_options(alias="countrysubdivisioncode")
    )
    homepage: str | None = None
    favicon: str | None = None
    load_balancer: str | None = field(
        default=None, metadata=field_options(alias="loadbalancer")
    )
    server_software: str | None = None
    sampling: int | None = None
    public: bool | None = None
    latitude: float | None = field(
        default=None, metadata=field_options(alias="geo_lat")
    )
    longitude: float | None = field(
        default=None, metadata=field_options(alias="geo_long")
    )


@dataclass
class StationClick(DataClassORJSONMixin):
    """Object information for a click on a station in the Radio Browser."""

    uuid: str = field(metadata=field_options(alias="clickuuid"))
    station_uuid: str = field(metadata=field_options(alias="stationuuid"))
    timestamp: datetime = field(metadata=field_options(alias="clicktimestamp_iso8601"))


@dataclass
class Country(DataClassORJSONMixin):
    """Object information for a Country from the Radio Browser."""

    code: str
    name: str
    station_count: int = field(metadata=field_options(alias="stationcount"))

    @property
    def favicon(self) -> str:
        """Return the favicon URL for the country.

        Returns
        -------
            URL to the favicon.

        """
        return f"https://flagcdn.com/256x192/{self.code.lower()}.png"


@dataclass
class Language(DataClassORJSONMixin):
    """Object information for a Language from the Radio Browser."""

    code: str | None = field(metadata=field_options(alias="iso_639"))
    name: str
    station_count: int = field(metadata=field_options(alias="stationcount"))

    @property
    def favicon(self) -> str | None:
        """Return the favicon URL for the language.

        Returns
        -------
            URL to the flag of the country the language belongs to, or None
            if there is no single country for it.

        """
        if self.code and (flag := LANGUAGE_FLAGS.get(self.code.lower())):
            return f"https://flagcdn.com/256x192/{flag}.png"
        return None


@dataclass
class Tag(DataClassORJSONMixin):
    """Object information for a Tag from the Radio Browser."""

    name: str
    station_count: int = field(metadata=field_options(alias="stationcount"))


@dataclass
class Codec(DataClassORJSONMixin):
    """Object information for a Codec from the Radio Browser."""

    name: str
    station_count: int = field(metadata=field_options(alias="stationcount"))


@dataclass
class State(DataClassORJSONMixin):
    """Object information for a State from the Radio Browser.

    States are entered by hand along with the stations, so expect anything
    from a province to a full street address.
    """

    name: str
    country: str
    station_count: int = field(metadata=field_options(alias="stationcount"))

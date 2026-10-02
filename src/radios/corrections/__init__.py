"""Corrections to the station data of the Radio Browser API.

The Radio Browser API has no way to edit a station, and its corrections
repository has not merged a fix in a long time. So this library ships its own:
JSON files in a folder per country, like ``fr/radio-odyssey.json``, each
holding corrections for one broadcaster or one topic. The format follows the
radio-database repository of Radio Browser, so a fix can travel between the
two.

A correction matches a station by its UUID. It either deletes the station, or
overwrites some of its fields, using the field names of the API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson
from probatio import (
    UUID,
    All,
    AtLeastOne,
    Latitude,
    Length,
    Longitude,
    Match,
    Optional,
    Required,
    Schema,
    Url,
    to_json_schema,
)

# Not imported as Any, which is the typing one here.
from probatio import Any as AnyOf

CORRECTIONS_PATH = Path(__file__).parent

# The station fields a correction can overwrite, with the value each takes.
# These are the names and formats of the API, so tags and languages are comma
# separated strings, like "news,pop".
FIELDS: dict[str, Any] = {
    "name": All(str, Length(min=1)),
    "url": Url(),
    # An empty homepage or favicon removes a broken one.
    "homepage": AnyOf(Url(), ""),
    "favicon": AnyOf(Url(), ""),
    "tags": str,
    "countrycode": Match(r"^[A-Z]{2}$"),
    "state": str,
    "iso_3166_2": Match(r"^[A-Z]{2}-[A-Z0-9]{1,3}$"),
    "language": str,
    "languagecodes": str,
    "geo_lat": Latitude(),
    "geo_long": Longitude(),
}

DELETION_SCHEMA = Schema(
    {
        Required("stationuuid"): UUID(),
        Required("reason"): All(str, Length(min=1)),
        Required("delete"): True,
    }
)

CHANGE_SCHEMA = All(
    Schema(
        {
            Required("stationuuid"): UUID(),
            Required("reason"): All(str, Length(min=1)),
            **{Optional(name): validator for name, validator in FIELDS.items()},
        }
    ),
    AtLeastOne(*FIELDS),
)

FILE_SCHEMA = Schema(
    {
        Required("$schema"): "../schema.json",
        Required("corrections"): All(
            [AnyOf(DELETION_SCHEMA, CHANGE_SCHEMA)], Length(min=1)
        ),
    }
)


def json_schema() -> dict[str, Any]:
    """Return the JSON Schema of a correction file, for editors to validate with.

    Returns
    -------
        The JSON Schema, as it is stored in ``schema.json``.

    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "python-radios station corrections",
        **to_json_schema(FILE_SCHEMA),
    }


def correction_files(path: Path = CORRECTIONS_PATH) -> list[Path]:
    """Return every correction file, in a stable order.

    Args:
    ----
        path: The folder holding a folder per country.

    Returns:
    -------
        The paths of the correction files.

    """
    return sorted(path.glob("*/*.json"))


def load_corrections(path: Path = CORRECTIONS_PATH) -> dict[str, dict[str, Any]]:
    """Load the corrections, by the UUID of the station they apply to.

    The files are not validated here: the test suite validates every one of
    them, so a broken file cannot end up in a release.

    Args:
    ----
        path: The folder holding a folder per country.

    Returns:
    -------
        The corrections, by station UUID.

    """
    corrections: dict[str, dict[str, Any]] = {}
    for file in correction_files(path):
        for correction in orjson.loads(file.read_bytes())["corrections"]:  # pylint: disable=no-member
            corrections[correction["stationuuid"]] = correction

    return corrections


def apply_corrections(
    stations: list[dict[str, Any]], corrections: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply the corrections to stations, as the API returned them.

    Args:
    ----
        stations: The stations, as dictionaries from the API.
        corrections: The corrections, by station UUID.

    Returns:
    -------
        The stations with their corrections, without the deleted ones.

    """
    corrected = []
    for station in stations:
        correction = corrections.get(station["stationuuid"])
        if correction is None:
            corrected.append(station)
            continue

        if correction.get("delete"):
            continue

        changes = {name: value for name, value in correction.items() if name in FIELDS}
        # The API resolves playlists into url_resolved. A corrected url makes
        # the resolved one stale, and it is the one players tend to use.
        if "url" in changes:
            changes["url_resolved"] = changes["url"]

        corrected.append(station | changes)

    return corrected

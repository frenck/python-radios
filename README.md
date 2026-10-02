# Python: Radio Browser API Client

[![GitHub Release][releases-shield]][releases]
[![Python Versions][python-versions-shield]][pypi]
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE.md)

[![Build Status][build-shield]][build]
[![Code Coverage][codecov-shield]][codecov]
[![OpenSSF Scorecard][scorecard-shield]][scorecard]
[![Open in Dev Containers][devcontainer-shield]][devcontainer]

[![Sponsor Frenck via GitHub Sponsors][github-sponsors-shield]][github-sponsors]

[![Support Frenck on Patreon][patreon-shield]][patreon]

Asynchronous Python client for the Radio Browser API.

## About

[Radio Browser](https://www.radio-browser.info) is a community driven effort
(like Wikipedia) with the aim of collecting as many internet radio and
TV stations as possible.

This Python library is an async API client for that, originally developed
for use with the [Home Assistant](https://www.home-assistant.io) project.

## Installation

```bash
pip install radios
```

## Usage

The client is an async context manager; every API call is a coroutine. The
Radio Browser project asks every app to identify itself, so a descriptive
user agent is required.

```python
"""Asynchronous Python client for the Radio Browser API."""

import asyncio

from radios import FilterBy, Order, RadioBrowser


async def main() -> None:
    """Show example on how to query the Radio Browser API."""
    async with RadioBrowser(user_agent="MyAwesomeApp/1.0.0") as radios:
        # The 10 most popular stations in the Netherlands
        stations = await radios.stations(
            filter_by=FilterBy.COUNTRY_CODE_EXACT,
            filter_term="NL",
            order=Order.CLICK_COUNT,
            reverse=True,
            limit=10,
        )
        for station in stations:
            print(f"{station.name} ({station.click_count} clicks)")

        # The best voted jazz stations that stream at 128 kbps or more
        stations = await radios.search(
            tag="jazz",
            bitrate_min=128,
            hide_broken=True,
            order=Order.VOTES,
            reverse=True,
            limit=10,
        )
        for station in stations:
            print(f"{station.name} ({station.codec}, {station.bitrate} kbps)")

        # Start playing a station: count the click, and get its stream URL
        if stations:
            url = await radios.station_click(uuid=stations[0].uuid)
            print(f"Now playing {stations[0].name}: {url}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Browsing stations

`stations()` lists stations, optionally filtered by one field with
`filter_by` and `filter_term`. All lists of stations, countries, languages,
tags, codecs and states take `order`, `reverse`, `limit`, `offset` and
`hide_broken`:

```python
from radios import FilterBy, Order

stations = await radios.stations(
    filter_by=FilterBy.TAG_EXACT,
    filter_term="classical",
    order=Order.VOTES,
    reverse=True,
    limit=25,
    hide_broken=True,
)

# A single station by its UUID, or None if it does not exist
station = await radios.station(uuid="d1a54d2e-623e-4970-ab11-35f7b56c5ec3")

# Several stations in one request, like refreshing a list of favorites
stations = await radios.stations_by_uuid(
    uuids=[
        "d1a54d2e-623e-4970-ab11-35f7b56c5ec3",
        "6c95ccdb-ca0a-4c59-a660-96e56ef2dca9",
    ]
)

# The stations behind a stream URL
stations = await radios.stations_by_url(
    url="https://icecast.walmradio.com:8443/classic"
)
```

### Searching

`search()` combines any number of filters. Text filters match part of a
value, unless you ask for an exact match:

```python
stations = await radios.search(
    country_code="US",
    language="english",
    tag_list=["jazz", "blues"],  # all of these tags
    codec="MP3",
    is_https=True,
)

# Stations within 25 kilometers of Amsterdam, nearest first
stations = await radios.search(geo_lat=52.37, geo_long=4.89, geo_distance=25_000)
for station in sorted(stations, key=lambda station: station.distance or 0):
    print(f"{station.name} ({station.distance:.0f} meters away)")
```

The results of a geo search carry their `distance` to the location, in
meters. On other results it is `None`.

Invalid combinations, like a `geo_distance` without a location, raise a
`ValueError`.

### Playing a station

Call `station_click()` when a user starts playing a station. It counts the
click, which helps Radio Browser rank popular stations, and returns the URL
to stream from:

```python
url = await radios.station_click(uuid=station.uuid)
```

If the user likes what they hear, `await radios.vote(uuid=station.uuid)`
votes for the station. The API counts one vote per station from the same IP
address every 10 minutes. When it does not accept a vote, `vote()` raises a
`RadioBrowserError`.

### Countries, languages, tags, codecs and states

```python
countries = await radios.countries()  # names resolved from ISO country codes
languages = await radios.languages(hide_broken=True)
tags = await radios.tags(order=Order.STATION_COUNT, reverse=True, limit=50)
codecs = await radios.codecs()
states = await radios.states(country_code="NL")

for country in countries:
    print(country.name, country.station_count, country.favicon)
```

They all take a `name` to only get the ones whose name contains it, like
`await radios.tags(name="jazz")`, which is handy for autocompletion.

Countries and languages have a `favicon` with a flag. A language that is not
tied to one country, like Arabic, has none.

States are entered by hand along with the stations, so expect anything from a
province to a full street address.

### Station history

The Radio Browser servers check every station regularly. The check history of
a station helps to find out why a stream does not play:

```python
checks = await radios.checks(uuid=station.uuid, seconds=86400)  # last day
for check in checks:
    print(check.timestamp, "online" if check.ok else "offline", check.codec)
```

`clicks()` works the same way, for when stations were played. Both continue
after an earlier result with `after=` and the UUID of the last check or click.

### Connection options

```python
RadioBrowser(
    user_agent="MyAwesomeApp/1.0.0",  # required, identifies your app
    request_timeout=8.0,  # per-request timeout in seconds
)
```

You may also pass your own `aiohttp.ClientSession` via `session=...` to
share a connection pool. The client then leaves closing it to you.

Without the async context manager, call `await radios.close()` when you are
done, to close the session the client created. A closed client can still be
used: the next request opens a new session.

Radio Browser runs on a pool of community servers. The client looks them up
through DNS and tries them in a random order: when a connection fails, it moves
on to the next server, with an exponential backoff in between, for up to five
attempts in total. When the DNS lookup of the servers fails, which some home
routers do with this kind of record, it uses `all.api.radio-browser.info`.

### Error handling

Everything that can go wrong while talking to the API raises a
`RadioBrowserError`, so a single `except` covers it all. Calling a method with
invalid arguments raises a plain `ValueError` instead, since that is a bug to
fix rather than a failure to handle.

```python
from radios import (
    RadioBrowser,
    RadioBrowserConnectionError,
    RadioBrowserError,
)

try:
    async with RadioBrowser(user_agent="MyAwesomeApp/1.0.0") as radios:
        stats = await radios.stats()
except RadioBrowserConnectionError:
    # Could not reach the API, even after retrying (includes timeouts)
    ...
except RadioBrowserError:
    # The API answered, but not with what we asked for (like a 404)
    ...
```

## Changelog & releases

This repository keeps a change log using [GitHub's releases][releases]
functionality. Releases are based on [Semantic Versioning][semver], and use the
format of `MAJOR.MINOR.PATCH`.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for
how to get started and what the review expects.

## Setting up development environment

This Python project is fully managed using the [Poetry][poetry] dependency
manager. But also relies on the use of NodeJS for certain checks during
development.

You need at least:

- Python 3.12+
- [Poetry][poetry-install]
- NodeJS 24+ (including NPM)

To install all packages, including all development requirements:

```bash
npm install
poetry install
```

As this repository uses the [prek][prek] framework, all changes
are linted and tested with each commit. You can run all checks and tests
manually, using the following command:

```bash
poetry run prek run --all-files
```

To run just the Python tests:

```bash
poetry run pytest
```

## Authors & contributors

The original setup of this repository is by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributor's page][contributors].

## Disclaimer

This project is an independent, community-driven effort. It is **not
affiliated with, endorsed by, or supported by** the Radio Browser project. All
station names, logos, and trademarks are property of their respective owners.

Station data comes from the public [Radio Browser API][radio-browser], which is
maintained by its community. This library does not host or verify any streams.

## License

MIT License

Copyright (c) 2022-2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[build-shield]: https://github.com/frenck/python-radios/actions/workflows/tests.yaml/badge.svg
[build]: https://github.com/frenck/python-radios/actions/workflows/tests.yaml
[codecov-shield]: https://codecov.io/gh/frenck/python-radios/branch/main/graph/badge.svg
[codecov]: https://codecov.io/gh/frenck/python-radios
[contributors]: https://github.com/frenck/python-radios/graphs/contributors
[devcontainer-shield]: https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode
[devcontainer]: https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/frenck/python-radios
[frenck]: https://github.com/frenck
[github-sponsors-shield]: https://frenck.dev/wp-content/uploads/2019/12/github_sponsor.png
[github-sponsors]: https://github.com/sponsors/frenck
[license-shield]: https://img.shields.io/github/license/frenck/python-radios.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[patreon-shield]: https://frenck.dev/wp-content/uploads/2019/12/patreon.png
[patreon]: https://www.patreon.com/frenck
[poetry-install]: https://python-poetry.org/docs/#installation
[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[project-stage-shield]: https://img.shields.io/badge/project%20stage-production%20ready-brightgreen.svg
[pypi]: https://pypi.org/project/radios/
[radio-browser]: https://www.radio-browser.info
[python-versions-shield]: https://img.shields.io/pypi/pyversions/radios
[releases-shield]: https://img.shields.io/github/release/frenck/python-radios.svg
[releases]: https://github.com/frenck/python-radios/releases
[scorecard]: https://scorecard.dev/viewer/?uri=github.com/frenck/python-radios
[scorecard-shield]: https://api.scorecard.dev/projects/github.com/frenck/python-radios/badge
[semver]: http://semver.org/spec/v2.0.0.html

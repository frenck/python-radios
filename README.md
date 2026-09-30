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

```python
# pylint: disable=W0621
"""Asynchronous Python client for the Radio Browser API."""

import asyncio

from radios import FilterBy, Order, RadioBrowser


async def main() -> None:
    """Show example on how to query the Radio Browser API."""
    async with RadioBrowser(user_agent="MyAwesomeApp/1.0.0") as radios:
        # Print top 10 stations
        stations = await radios.stations(
            limit=10, order=Order.CLICK_COUNT, reverse=True
        )
        for station in stations:
            print(f"{station.name} ({station.click_count})")

        # Get a specific station
        print(await radios.station(uuid="9608b51d-0601-11e8-ae97-52543be04c81"))

        # Print top 10 stations in a country
        stations = await radios.stations(
            limit=10,
            order=Order.CLICK_COUNT,
            reverse=True,
            filter_by=FilterBy.COUNTRY_CODE_EXACT,
            filter_term="NL",
        )
        for station in stations:
            print(f"{station.name} ({station.click_count})")

        # Register a station "click"
        await radios.station_click(uuid="9608b51d-0601-11e8-ae97-52543be04c81")

        # Tags, countries and codes.
        print(await radios.tags(limit=10, order=Order.STATION_COUNT, reverse=True))
        print(await radios.countries(limit=10, order=Order.NAME))
        print(await radios.languages(limit=10, order=Order.NAME))


if __name__ == "__main__":
    asyncio.run(main())
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

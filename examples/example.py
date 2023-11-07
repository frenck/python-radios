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
        print(await radios.search(name="538", limit=10, order=Order.NAME))


if __name__ == "__main__":
    asyncio.run(main())

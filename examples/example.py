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

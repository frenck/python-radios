"""Asynchronous Python client for the Radio Browser API."""

from __future__ import annotations

import asyncio
import random
import socket
import unicodedata
from asyncio import sleep
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import quote

import aiohttp
import orjson
from aiodns import DNSResolver
from aiodns.error import DNSError
from aiohttp import hdrs
from pycares import SRVRecordData
from yarl import URL

from .const import LIST_ORDERS, STATION_ORDERS, FilterBy, Order
from .exceptions import (
    RadioBrowserConnectionError,
    RadioBrowserConnectionTimeoutError,
    RadioBrowserError,
)
from .models import Country, Language, Station, Stats, Tag, country_name

if TYPE_CHECKING:
    from collections.abc import Iterator

# How often a request is tried when the connection to the API fails.
REQUEST_ATTEMPTS = 5


@contextmanager
def unexpected_response() -> Iterator[None]:
    """Turn a response that cannot be parsed into a RadioBrowserError.

    The API answered, but with JSON that is broken or does not look like what
    it documents: a missing field, a wrong type, an object where a list
    belongs. That is a problem with the response, not with the caller, so it
    should surface like any other API error instead of as a raw parser error.

    Raises
    ------
        RadioBrowserError: The response could not be parsed.

    """
    try:
        yield
    except (AttributeError, LookupError, TypeError, ValueError) as exception:
        msg = "Unexpected response from the Radio Browser API"
        raise RadioBrowserError(msg) from exception


def name_sort_key(name: str) -> str:
    """Return a key that sorts names the way people expect.

    Sorting on the plain string puts every accented letter after "Z", so
    "Åland Islands" would come after "Zimbabwe". Comparing the names without
    their accents, and ignoring case, keeps them where a reader looks.

    Args:
    ----
        name: The name to sort.

    Returns:
    -------
        The sort key for the name.

    """
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return unaccented.casefold()


def validate_order(order: Order, allowed: frozenset[Order]) -> None:
    """Make sure the endpoint can sort by the requested order.

    Args:
    ----
        order: The requested order.
        allowed: The orders the endpoint supports.

    Raises:
    ------
        ValueError: The endpoint cannot sort by this order.

    """
    if order not in allowed:
        supported = ", ".join(sorted(f"Order.{item.name}" for item in allowed))
        msg = f"Cannot order by Order.{order.name} here, use one of: {supported}"
        raise ValueError(msg)


def validate_paging(limit: int, offset: int) -> None:
    """Make sure the paging arguments are not negative.

    Args:
    ----
        limit: The requested number of results.
        offset: The requested number of results to skip.

    Raises:
    ------
        ValueError: The limit or offset is negative.

    """
    if limit < 0 or offset < 0:
        msg = f"limit and offset cannot be negative, got {limit=} and {offset=}"
        raise ValueError(msg)


def stations_from_json(data: str) -> list[Station]:
    """Parse a list of stations from an API response.

    Args:
    ----
        data: The JSON response, a list of stations.

    Returns:
    -------
        A list of Station objects.

    Raises:
    ------
        RadioBrowserError: The response could not be parsed.

    """
    with unexpected_response():
        stations = orjson.loads(data)  # pylint: disable=no-member
        # pylint: disable-next=not-an-iterable
        return [Station.from_dict(station) for station in stations]


# The stations/search endpoint has no by* paths, so search() turns each
# FilterBy value into search query parameters instead.
SEARCH_FILTERS: dict[FilterBy, tuple[str, dict[str, bool]]] = {
    FilterBy.NAME: ("name", {"nameExact": False}),
    FilterBy.NAME_EXACT: ("name", {"nameExact": True}),
    FilterBy.CODEC_EXACT: ("codec", {}),
    FilterBy.COUNTRY: ("country", {"countryExact": False}),
    FilterBy.COUNTRY_EXACT: ("country", {"countryExact": True}),
    FilterBy.COUNTRY_CODE_EXACT: ("countrycode", {}),
    FilterBy.STATE: ("state", {"stateExact": False}),
    FilterBy.STATE_EXACT: ("state", {"stateExact": True}),
    FilterBy.LANGUAGE: ("language", {"languageExact": False}),
    FilterBy.LANGUAGE_EXACT: ("language", {"languageExact": True}),
    FilterBy.TAG: ("tag", {"tagExact": False}),
    FilterBy.TAG_EXACT: ("tag", {"tagExact": True}),
}


@dataclass
class RadioBrowser:
    """Main class for handling connections with the Radio Browser API."""

    user_agent: str

    request_timeout: float = 8.0
    session: aiohttp.client.ClientSession | None = None

    _close_session: bool = False
    _host: str | None = None

    async def _resolve_host(self) -> str:
        """Pick one of the Radio Browser API servers.

        The API does not have a fixed host. Its servers are published as DNS
        SRV records, and clients are asked to spread their load by picking one
        at random.

        Returns
        -------
            The host name of a Radio Browser API server.

        Raises
        ------
            RadioBrowserConnectionError: The API servers could not be looked up.

        """
        try:
            result = await DNSResolver().query_dns(
                "_api._tcp.radio-browser.info", "SRV"
            )
        except DNSError as exception:
            msg = "Error occurred while looking up the Radio Browser API servers"
            raise RadioBrowserConnectionError(msg) from exception

        hosts = [
            record.data.target
            for record in result.answer
            if isinstance(record.data, SRVRecordData)
        ]
        if not hosts:
            msg = "No Radio Browser API servers found"
            raise RadioBrowserConnectionError(msg)

        return random.choice(hosts)  # noqa: S311

    async def _request(
        self,
        uri: str = "",
        method: str = hdrs.METH_GET,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Handle a request to the Radio Browser API, retrying connection errors.

        A failed connection makes the client forget its API server, so each
        retry may land on a different one. The wait between attempts grows
        exponentially, with full jitter so clients that failed together do
        not all retry at the same moment.

        Args:
        ----
            uri: Request URI, for example `stats`. Any user provided parts
                of it must already be URL encoded.
            method: HTTP method to use for the request, for example "GET".
            params: Dictionary of data to send to the Radio Browser API.

        Returns:
        -------
            The response from the Radio Browser API.

        """
        for attempt in range(REQUEST_ATTEMPTS - 1):
            try:
                return await self._request_once(uri, method, params)
            except RadioBrowserConnectionError:
                await sleep(random.uniform(0, 2**attempt))  # noqa: S311

        return await self._request_once(uri, method, params)

    async def _request_once(
        self,
        uri: str,
        method: str,
        params: dict[str, Any] | None,
    ) -> str:
        """Send a single request to the Radio Browser API.

        A generic method for sending/handling HTTP requests done against
        the Radio Browser API.

        Args:
        ----
            uri: Request URI, for example `stats`. Any user provided parts
                of it must already be URL encoded.
            method: HTTP method to use for the request, for example "GET".
            params: Dictionary of data to send to the Radio Browser API.

        Returns:
        -------
            The response from the Radio Browser API.

        Raises:
        ------
            RadioBrowserConnectionError: An error occurred while communicating
                with the Radio Browser API.
            RadioBrowserConnectionTimeoutError: A timeout occurred while communicating
                with the Radio Browser API.
            RadioBrowserError: Received an unexpected response from the
                Radio Browser API.

        """
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True

        # Build a new dict, so the caller's own params are left untouched.
        if params:
            params = {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in params.items()
            }
        try:
            async with asyncio.timeout(self.request_timeout):
                # Looking up the server is part of the request, so a DNS
                # server that does not answer runs into the same timeout.
                if self._host is None:
                    self._host = await self._resolve_host()

                url = URL.build(
                    scheme="https", host=self._host, path=f"/json/{uri}", encoded=True
                )
                response = await self.session.request(
                    method,
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/json",
                    },
                    params=params,
                    raise_for_status=True,
                )
                text = await response.text()

            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                raise RadioBrowserError(response.status, {"message": text})
        except TimeoutError as exception:
            self._host = None
            msg = "Timeout occurred while connecting to the Radio Browser API"
            raise RadioBrowserConnectionTimeoutError(msg) from exception
        except UnicodeDecodeError as exception:
            # The body does not match the encoding the server claims. That is
            # a broken response, not a connection problem, so it is not retried.
            msg = "Unexpected response from the Radio Browser API"
            raise RadioBrowserError(msg) from exception
        except aiohttp.ClientResponseError as exception:
            # A client error is our mistake, like an unknown station. Asking
            # again, or asking another server, will not change the answer.
            if exception.status < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise RadioBrowserError(
                    exception.status, {"message": exception.message}
                ) from exception

            self._host = None
            msg = "Error occurred while communicating with the Radio Browser API"
            raise RadioBrowserConnectionError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            self._host = None
            msg = "Error occurred while communicating with the Radio Browser API"
            raise RadioBrowserConnectionError(msg) from exception

        return text

    async def stats(self) -> Stats:
        """Get Radio Browser service stats.

        Returns
        -------
            A Stats object, with information about the Radio Browser API.

        """
        response = await self._request("stats")
        with unexpected_response():
            return Stats.from_json(response)

    async def station_click(self, *, uuid: str) -> str:
        """Register click on a station.

        Increase the click count of a station by one. This should be called
        every time when a user starts playing a stream to mark the stream more
        popular than others. Every call to this endpoint from the same IP
        address and for the same station only gets counted once per day.

        Args:
        ----
            uuid: UUID of the station.

        Returns:
        -------
            The stream URL of the station, ready to play.

        """
        click_data = await self._request(f"url/{quote(uuid, safe='')}")
        with unexpected_response():
            click = orjson.loads(click_data)  # pylint: disable=no-member
            return click["url"]

    # pylint: disable-next=too-many-arguments
    async def countries(
        self,
        *,
        hide_broken: bool = False,
        limit: int = 100000,
        offset: int = 0,
        order: Order = Order.NAME,
        reverse: bool = False,
    ) -> list[Country]:
        """Get list of available countries.

        Args:
        ----
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of Country objects.

        Raises:
        ------
            ValueError: The endpoint cannot sort by this order, or the limit
                or offset is negative.

        """
        validate_order(order, LIST_ORDERS)
        validate_paging(limit, offset)

        # The API only knows country codes, so it sorts "by name" on the code,
        # and it lists a code in lowercase as a country of its own. The whole
        # list is fetched instead (it is short), cleaned up, and sorted and
        # paged here.
        countries_data = await self._request(
            "countrycodes", params={"hidebroken": hide_broken}
        )

        with unexpected_response():
            countries: dict[str, dict[str, Any]] = {}
            # pylint: disable-next=not-an-iterable
            for country in orjson.loads(countries_data):  # pylint: disable=no-member
                # A few stations carry their code in lowercase, like "de".
                # Filtering on "DE" already includes those, so they belong to
                # the same country.
                code = country["name"].upper()
                if code in countries:
                    countries[code]["stationcount"] += country["stationcount"]
                    continue

                countries[code] = {
                    "code": code,
                    "name": country_name(code) or code,
                    "stationcount": country["stationcount"],
                }

            # Sorting by name first keeps countries with the same station
            # count in alphabetical order.
            ordered = sorted(
                countries.values(), key=lambda country: name_sort_key(country["name"])
            )
            if order == Order.STATION_COUNT:
                ordered.sort(key=lambda country: country["stationcount"])
            if reverse:
                ordered.reverse()

            return [
                Country.from_dict(country)
                for country in ordered[offset : offset + limit]
            ]

    # pylint: disable-next=too-many-arguments
    async def languages(
        self,
        *,
        hide_broken: bool = False,
        limit: int = 100000,
        offset: int = 0,
        order: Order = Order.NAME,
        reverse: bool = False,
    ) -> list[Language]:
        """Get list of available languages.

        Args:
        ----
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of Language objects.

        Raises:
        ------
            ValueError: The endpoint cannot sort by this order, or the limit
                or offset is negative.

        """
        validate_order(order, LIST_ORDERS)
        validate_paging(limit, offset)

        languages_data = await self._request(
            "languages",
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )

        with unexpected_response():
            languages = orjson.loads(languages_data)  # pylint: disable=no-member
            for language in languages:  # pylint: disable=not-an-iterable
                language["name"] = language["name"].title()

            # pylint: disable-next=not-an-iterable
            return [Language.from_dict(language) for language in languages]

    # pylint: disable-next=too-many-arguments, too-many-locals
    async def search(  # noqa: PLR0913
        self,
        *,
        filter_by: FilterBy | None = None,
        filter_term: str | None = None,
        hide_broken: bool = False,
        limit: int = 100000,
        offset: int = 0,
        order: Order = Order.NAME,
        reverse: bool = False,
        name: str | None = None,
        name_exact: bool = False,
        country: str | None = None,
        country_exact: bool = False,
        country_code: str | None = None,
        state: str | None = None,
        state_exact: bool = False,
        language: str | None = None,
        language_exact: bool = False,
        tag: str | None = None,
        tag_exact: bool = False,
        tag_list: list[str] | None = None,
        codec: str | None = None,
        bitrate_min: int = 0,
        bitrate_max: int = 1000000,
        is_https: bool | None = None,
        has_geo_info: bool | None = None,
        has_extended_info: bool | None = None,
        geo_lat: float | None = None,
        geo_long: float | None = None,
        geo_distance: float | None = None,
    ) -> list[Station]:
        """Get list of radio stations.

        Args:
        ----
            filter_by: Filter the results by a specific field. It overrides
                the matching search parameters, for example `name` and
                `name_exact` for `FilterBy.NAME`. `FilterBy.UUID` and
                `FilterBy.CODEC` are not supported.
            filter_term: Search term to filter the results.
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.
            name: Search by name.
            name_exact: Search by exact name.
            country: Search by country.
            country_exact: Search by exact country.
            country_code: Search by country code.
            state: Search by state.
            state_exact: Search by exact state.
            language: Search by language.
            language_exact: Search by exact language.
            tag: Search by tag.
            tag_exact: Search by exact tag.
            tag_list: Only stations that match all of these tags. Like
                `tag`, this matches part of a tag: "blues" also finds
                "blues rock".
            codec: Search by codec, for example "MP3" or "AAC".
            bitrate_min: Search by minimum bitrate.
            bitrate_max: Search by maximum bitrate.
            is_https: Only stations that stream over HTTPS when True, or
                only plain HTTP ones when False. Both when not set.
            has_geo_info: Only stations with a location when True, or only
                stations without one when False. Both when not set.
            has_extended_info: Only stations that provide extended
                information when True, or only ones that do not when False.
                Both when not set.
            geo_lat: Latitude to search around, together with geo_long.
            geo_long: Longitude to search around, together with geo_lat.
            geo_distance: Only stations within this many meters of geo_lat
                and geo_long.

        Returns:
        -------
            A list of Station objects.

        Raises:
        ------
            ValueError: The filter_by value is not supported, filter_term
                is missing, the location for a geo search is incomplete, the
                endpoint cannot sort by this order, or the limit or offset is
                negative.

        """
        location_incomplete = (geo_lat is None) != (geo_long is None)
        if location_incomplete or (geo_distance is not None and geo_lat is None):
            msg = "geo_lat and geo_long must be set together, also for geo_distance"
            raise ValueError(msg)

        validate_order(order, STATION_ORDERS)
        validate_paging(limit, offset)

        params: dict[str, Any] = {
            "hidebroken": hide_broken,
            "offset": offset,
            "order": order.value,
            "reverse": reverse,
            "limit": limit,
            "name": name,
            "nameExact": name_exact,
            "country": country,
            "countryExact": country_exact,
            "countrycode": country_code,
            "state": state,
            "stateExact": state_exact,
            "language": language,
            "languageExact": language_exact,
            "tag": tag,
            "tagExact": tag_exact,
            "tagList": ",".join(tag_list) if tag_list else None,
            "codec": codec,
            "bitrateMin": bitrate_min,
            "bitrateMax": bitrate_max,
            "is_https": is_https,
            "has_geo_info": has_geo_info,
            "has_extended_info": has_extended_info,
            "geo_lat": geo_lat,
            "geo_long": geo_long,
            "geo_distance": geo_distance,
        }

        if filter_by is not None:
            if filter_by not in SEARCH_FILTERS:
                msg = f"search() does not support filter_by {filter_by.name}"
                raise ValueError(msg)
            if filter_term is None:
                msg = "filter_by requires a filter_term"
                raise ValueError(msg)

            key, flags = SEARCH_FILTERS[filter_by]
            params.update({key: filter_term, **flags})

        stations_data = await self._request(
            "stations/search",
            # yarl rejects None as a query value, so unset filters are left out.
            params={key: value for key, value in params.items() if value is not None},
        )
        return stations_from_json(stations_data)

    async def station(self, *, uuid: str) -> Station | None:
        """Get station by UUID.

        Args:
        ----
            uuid: UUID of the station.

        Returns:
        -------
            A  Station object if found.

        """
        stations = await self.stations(
            filter_by=FilterBy.UUID,
            filter_term=uuid,
            limit=1,
        )
        if not stations:
            return None
        return stations[0]

    async def stations_by_uuid(self, *, uuids: list[str]) -> list[Station]:
        """Get several stations by their UUID, in a single request.

        Useful to refresh a list of favorite stations. UUIDs of stations that
        do not exist (anymore) are left out of the result.

        Args:
        ----
            uuids: UUIDs of the stations.

        Returns:
        -------
            A list of Station objects.

        """
        if not uuids:
            return []

        stations_data = await self._request(
            "stations/byuuid", params={"uuids": ",".join(uuids)}
        )
        return stations_from_json(stations_data)

    async def stations_by_url(self, *, url: str) -> list[Station]:
        """Get the stations that stream from a URL.

        Useful to find the station behind a saved stream URL. Several
        stations can share a stream, so this can return more than one.

        Args:
        ----
            url: The stream URL, as given or as resolved.

        Returns:
        -------
            A list of Station objects.

        """
        stations_data = await self._request("stations/byurl", params={"url": url})
        return stations_from_json(stations_data)

    # pylint: disable-next=too-many-arguments
    async def stations(  # noqa: PLR0913
        self,
        *,
        filter_by: FilterBy | None = None,
        filter_term: str | None = None,
        hide_broken: bool = False,
        limit: int = 100000,
        offset: int = 0,
        order: Order = Order.NAME,
        reverse: bool = False,
    ) -> list[Station]:
        """Get list of radio stations.

        Args:
        ----
            filter_by: Filter the results by a specific field.
            filter_term: Search term to filter the results.
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of Station objects.

        Raises:
        ------
            ValueError: The endpoint cannot sort by this order, the limit or
                offset is negative, or filter_by is set without a filter_term.

        """
        validate_order(order, STATION_ORDERS)
        validate_paging(limit, offset)

        uri = "stations"
        if filter_by is not None:
            # Every by* path needs a term, without one the API answers 404.
            if filter_term is None:
                msg = "filter_by requires a filter_term"
                raise ValueError(msg)

            # Terms like "#original" or "AC/DC" would otherwise change the URL
            # instead of being part of it.
            uri = f"{uri}/{filter_by.value}/{quote(filter_term, safe='')}"

        stations_data = await self._request(
            uri,
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )
        return stations_from_json(stations_data)

    # pylint: disable-next=too-many-arguments
    async def tags(
        self,
        *,
        hide_broken: bool = False,
        limit: int = 100000,
        offset: int = 0,
        order: Order = Order.NAME,
        reverse: bool = False,
    ) -> list[Tag]:
        """Get list of available tags.

        Args:
        ----
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of Tags objects.

        Raises:
        ------
            ValueError: The endpoint cannot sort by this order, or the limit
                or offset is negative.

        """
        validate_order(order, LIST_ORDERS)
        validate_paging(limit, offset)

        tags_data = await self._request(
            "tags",
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )
        with unexpected_response():
            tags = orjson.loads(tags_data)  # pylint: disable=no-member
            # pylint: disable-next=not-an-iterable
            return [Tag.from_dict(tag) for tag in tags]

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

            # Forget the closed session, so the client can be used again: the
            # next request opens a fresh session, instead of failing on this one.
            self.session = None
            self._close_session = False

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The RadioBrowser object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exec type.

        """
        await self.close()

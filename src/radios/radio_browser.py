"""Asynchronous Python client for the Radio Browser API."""

from __future__ import annotations

import asyncio
import random
import socket
from asyncio import sleep
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Self
from urllib.parse import quote

import aiohttp
import orjson
from aiodns import DNSResolver
from aiodns.error import DNSError
from aiohttp import hdrs
from pycares import SRVRecordData
from yarl import URL

from .const import FilterBy, Order
from .exceptions import (
    RadioBrowserConnectionError,
    RadioBrowserConnectionTimeoutError,
    RadioBrowserError,
)
from .models import Country, Language, Station, Stats, Tag, country_name

# How often a request is tried when the connection to the API fails.
REQUEST_ATTEMPTS = 5

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
        if self._host is None:
            self._host = await self._resolve_host()

        url = URL.build(
            scheme="https", host=self._host, path=f"/json/{uri}", encoded=True
        )

        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True

        if params:
            for key, value in params.items():
                if isinstance(value, bool):
                    params[key] = str(value).lower()
        try:
            async with asyncio.timeout(self.request_timeout):
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

        """
        countries_data = await self._request(
            "countrycodes",
            params={
                "hidebroken": hide_broken,
                "limit": limit,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
            },
        )

        countries = orjson.loads(countries_data)  # pylint: disable=no-member
        for country in countries:  # pylint: disable=not-an-iterable
            country["code"] = country["name"]
            country["name"] = country_name(country["code"]) or country["code"]

        # Because we enriched the countries we need to re-order in this case
        if order == Order.NAME:
            countries.sort(key=lambda country: country["name"])

        # pylint: disable-next=not-an-iterable
        return [Country.from_dict(country) for country in countries]

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

        """
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
        bitrate_min: int = 0,
        bitrate_max: int = 1000000,
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
            bitrate_min: Search by minimum bitrate.
            bitrate_max: Search by maximum bitrate.

        Returns:
        -------
            A list of Station objects.

        Raises:
        ------
            ValueError: The filter_by value is not supported, or
                filter_term is missing.

        """
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
            "bitrateMin": bitrate_min,
            "bitrateMax": bitrate_max,
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
        stations = orjson.loads(stations_data)  # pylint: disable=no-member
        # pylint: disable-next=not-an-iterable
        return [Station.from_dict(station) for station in stations]

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

        """
        uri = "stations"
        if filter_by is not None:
            uri = f"{uri}/{filter_by.value}"
            if filter_term is not None:
                # Terms like "#original" or "AC/DC" would otherwise change
                # the URL instead of being part of it.
                uri = f"{uri}/{quote(filter_term, safe='')}"

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
        stations = orjson.loads(stations_data)  # pylint: disable=no-member
        # pylint: disable-next=not-an-iterable
        return [Station.from_dict(station) for station in stations]

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

        """
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
        tags = orjson.loads(tags_data)  # pylint: disable=no-member
        # pylint: disable-next=not-an-iterable
        return [Tag.from_dict(tag) for tag in tags]

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

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

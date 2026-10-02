"""Asynchronous Python client for the Radio Browser API."""

from __future__ import annotations

import asyncio
import logging
import random
import socket
import unicodedata
from asyncio import sleep
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any, Self
from urllib.parse import quote

import aiohttp
import orjson
from aiodns import DNSResolver
from aiodns.error import DNSError
from aiohttp import hdrs
from probatio import In, Latitude, Longitude, NonNegative, probatio
from pycares import SRVRecordData
from yarl import URL

from .const import LIST_ORDERS, STATION_ORDERS, FilterBy, Order
from .corrections import apply_corrections, load_corrections
from .exceptions import (
    RadioBrowserConnectionError,
    RadioBrowserConnectionTimeoutError,
    RadioBrowserError,
    RadioBrowserValidationError,
)
from .models import (
    Codec,
    Country,
    Language,
    State,
    Station,
    StationCheck,
    StationClick,
    Stats,
    Tag,
    country_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOGGER = logging.getLogger(__name__)

# Argument types the public methods validate, with probatio, before a request
# is sent. Not every endpoint can sort by every order; see LIST_ORDERS and
# STATION_ORDERS in const.py.
Count = Annotated[int, NonNegative()]
ListOrder = Annotated[Order, In(LIST_ORDERS)]
StationOrder = Annotated[Order, In(STATION_ORDERS)]

# How often a request is tried when the connection to the API fails.
REQUEST_ATTEMPTS = 5

# The API servers are published as DNS SRV records. Some home routers and DNS
# filters do not handle those well, so when that lookup fails, this host name
# is used instead. Its plain A and AAAA records point to all API servers.
SRV_RECORD = "_api._tcp.radio-browser.info"
FALLBACK_HOST = "all.api.radio-browser.info"

# The corrections this library ships for the station data of the API, see the
# corrections package. They are read once, on import: reading files from the
# event loop would block it, and an asyncio application like Home Assistant
# imports its libraries outside of it.
CORRECTIONS = load_corrections()


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


def list_from_json(data: str) -> list[Any]:
    """Parse an API response that should be a list.

    An object or a string where a list belongs would otherwise pass as an
    empty list, hiding a broken response. Call this inside
    unexpected_response(), which turns the error into a RadioBrowserError.

    Args:
    ----
        data: The JSON response.

    Returns:
    -------
        The parsed list.

    Raises:
    ------
        TypeError: The response is not a list.

    """
    items = orjson.loads(data)  # pylint: disable=no-member
    if not isinstance(items, list):
        msg = f"Expected a list, got {type(items).__name__}"
        raise TypeError(msg)
    return items


def stations_from_json(
    data: str, corrections: dict[str, dict[str, Any]]
) -> list[Station]:
    """Parse a list of stations from an API response, and correct them.

    Args:
    ----
        data: The JSON response, a list of stations.
        corrections: The corrections to apply, by station UUID.

    Returns:
    -------
        A list of Station objects.

    Raises:
    ------
        RadioBrowserError: The response could not be parsed.

    """
    with unexpected_response():
        stations = apply_corrections(list_from_json(data), corrections)
        return [Station.from_dict(station) for station in stations]


def name_filter_uri(uri: str, name: str | None) -> str:
    """Add a name filter to the URI of a list endpoint.

    The API matches part of a name, but case sensitive, on names it stores
    in lowercase. Searching for "Dutch" would find nothing, so the filter is
    lowercased first.

    Args:
    ----
        uri: The URI of the list endpoint, for example `tags`.
        name: Part of the name to filter on, if any.

    Returns:
    -------
        The URI, with the filter added when there is one.

    """
    if not name:
        return uri
    return f"{uri}/{quote(name.lower(), safe='')}"


# The API stores tags and languages in lowercase and matches them case
# sensitive, so "Jazz" or "Dutch" would find nothing. Their filter values are
# lowercased before they are sent.
LOWERCASE_FILTERS = frozenset(
    {FilterBy.LANGUAGE, FilterBy.LANGUAGE_EXACT, FilterBy.TAG, FilterBy.TAG_EXACT}
)


def lowercase(value: str | None) -> str | None:
    """Lowercase a filter value, if there is one.

    Args:
    ----
        value: The filter value.

    Returns:
    -------
        The lowercased value, or None when there is no value.

    """
    return value.lower() if value is not None else None


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
    # Apply the corrections this library ships for the station data. Turn
    # them off to get the stations exactly as the API returns them.
    corrections: bool = True

    _close_session: bool = False
    _host: str | None = None
    # The servers not tried yet, in the random order they will be tried in.
    _hosts: list[str] = field(default_factory=list)
    # The names the API uses for countries, by country code. They hardly ever
    # change, so they are looked up once per client.
    _api_country_names: dict[str, str] | None = None
    _api_country_names_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def _corrections(self) -> dict[str, dict[str, Any]]:
        """Return the corrections to apply, none when they are turned off."""
        return CORRECTIONS if self.corrections else {}

    async def _resolve_hosts(self) -> list[str]:
        """Look up the Radio Browser API servers, in a random order.

        The API does not have a fixed host. Its servers are published as DNS
        SRV records, and clients are asked to pick one at random and, when a
        request fails, to try the next one.

        Returns
        -------
            The host names of the Radio Browser API servers, shuffled. When
            the servers cannot be looked up, the fallback host name.

        """
        try:
            # Some routers silently drop SRV queries instead of refusing them.
            # Give the lookup half of the request timeout, so a lookup that
            # never answers still leaves time to fall back to the other host
            # name. The resolver is closed also when the lookup is cut short:
            # a lookup left pending in an unclosed resolver can crash the
            # Python process once the event loop shuts down.
            async with (
                asyncio.timeout(self.request_timeout / 2),
                DNSResolver() as resolver,
            ):
                result = await resolver.query_dns(SRV_RECORD, "SRV")
        except (DNSError, TimeoutError) as exception:
            _LOGGER.debug(
                "Could not look up the Radio Browser API servers (%r), using %s",
                exception,
                FALLBACK_HOST,
            )
            return [FALLBACK_HOST]

        hosts = [
            record.data.target
            for record in result.answer
            if isinstance(record.data, SRVRecordData)
        ]
        if not hosts:
            _LOGGER.debug("No Radio Browser API servers found, using %s", FALLBACK_HOST)
            return [FALLBACK_HOST]

        random.shuffle(hosts)
        _LOGGER.debug("Found Radio Browser API servers: %s", ", ".join(hosts))
        return hosts

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
            except RadioBrowserConnectionError as exception:
                delay = random.uniform(0, 2**attempt)  # noqa: S311
                _LOGGER.debug(
                    "Request %s failed on attempt %d of %d (%r), retrying in %.1fs",
                    uri,
                    attempt + 1,
                    REQUEST_ATTEMPTS,
                    exception.__cause__ or exception,
                    delay,
                )
                await sleep(delay)

        return await self._request_once(uri, method, params)

    def _forget_host(self, host: str | None) -> None:
        """Stop using a server after a request to it failed.

        Requests run concurrently, so by the time one fails, another may have
        moved on to the next server already and be doing fine there. Only
        forget the server this request was actually using. A request that
        failed before it picked a server has none to forget.

        Args:
        ----
            host: The server the failed request used, if it got that far.

        """
        if host is not None and self._host == host:
            self._host = None

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
        # Hold on to the session, close() may let go of it while this request
        # waits for the server lookup.
        session = self.session

        # Build a new dict, so the caller's own params are left untouched.
        if params:
            params = {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in params.items()
            }
        host: str | None = None
        try:
            async with asyncio.timeout(self.request_timeout):
                # Looking up the server is part of the request, so a DNS
                # server that does not answer runs into the same timeout.
                if self._host is None:
                    # Move on to the next server, and look them up again only
                    # once every one of them has been tried.
                    if not self._hosts:
                        self._hosts = await self._resolve_hosts()
                    self._host = self._hosts.pop(0)
                    _LOGGER.debug("Using Radio Browser API server %s", self._host)
                host = self._host

                if session.closed:
                    msg = "The Radio Browser client was closed during the request"
                    raise RadioBrowserError(msg)

                url = URL.build(
                    scheme="https", host=host, path=f"/json/{uri}", encoded=True
                )
                response = await session.request(
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
            self._forget_host(host)
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

            self._forget_host(host)
            msg = "Error occurred while communicating with the Radio Browser API"
            raise RadioBrowserConnectionError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            self._forget_host(host)
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

    @probatio(error=RadioBrowserValidationError)
    async def checks(
        self,
        *,
        uuid: str | None = None,
        after: str | None = None,
        seconds: Count | None = None,
        limit: Count = 100000,
    ) -> list[StationCheck]:
        """Get the results of the checks the Radio Browser does on stations.

        With a station UUID, this is the check history of that station, which
        helps to find out why a stream does not play. Without one, it is the
        latest check of every station.

        Args:
        ----
            uuid: Only the checks of the station with this UUID.
            after: Only the checks after the check with this UUID, to continue
                where an earlier call left off.
            seconds: Only the checks of the last this many seconds. Zero
                means no time limit, like leaving it out.
            limit: Limit the number of results.

        Returns:
        -------
            A list of StationCheck objects.

        Raises:
        ------
            RadioBrowserValidationError: The limit or seconds is negative.

        """
        checks_data = await self._history(
            "checks",
            uuid=uuid,
            after=("lastcheckuuid", after),
            seconds=seconds,
            limit=limit,
        )
        with unexpected_response():
            checks = list_from_json(checks_data)
            # pylint: disable-next=not-an-iterable
            return [StationCheck.from_dict(check) for check in checks]

    @probatio(error=RadioBrowserValidationError)
    async def clicks(
        self,
        *,
        uuid: str | None = None,
        after: str | None = None,
        seconds: Count | None = None,
        limit: Count = 100000,
    ) -> list[StationClick]:
        """Get the clicks on stations, that is, when they were played.

        Args:
        ----
            uuid: Only the clicks on the station with this UUID.
            after: Only the clicks after the click with this UUID, to continue
                where an earlier call left off.
            seconds: Only the clicks of the last this many seconds. Zero
                means no time limit, like leaving it out.
            limit: Limit the number of results.

        Returns:
        -------
            A list of StationClick objects.

        Raises:
        ------
            RadioBrowserValidationError: The limit or seconds is negative.

        """
        clicks_data = await self._history(
            "clicks",
            uuid=uuid,
            after=("lastclickuuid", after),
            seconds=seconds,
            limit=limit,
        )
        with unexpected_response():
            clicks = list_from_json(clicks_data)
            # pylint: disable-next=not-an-iterable
            return [StationClick.from_dict(click) for click in clicks]

    async def _history(
        self,
        endpoint: str,
        *,
        uuid: str | None,
        after: tuple[str, str | None],
        seconds: int | None,
        limit: int,
    ) -> str:
        """Request the check or click history, of one or all stations.

        Args:
        ----
            endpoint: The history endpoint, "checks" or "clicks".
            uuid: Only the history of the station with this UUID.
            after: The name of the parameter that continues after an earlier
                result, and the UUID to continue after.
            seconds: Only the history of the last this many seconds. Zero
                means no time limit, like leaving it out.
            limit: Limit the number of results.

        Returns:
        -------
            The response from the Radio Browser API.

        """
        uri = endpoint
        if uuid:
            uri = f"{uri}/{quote(uuid, safe='')}"

        after_param, after_uuid = after
        params = {after_param: after_uuid, "seconds": seconds, "limit": limit}
        return await self._request(
            uri,
            # yarl rejects None as a query value, so unset filters are left out.
            params={key: value for key, value in params.items() if value is not None},
        )

    @probatio(error=RadioBrowserValidationError)
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

        Raises:
        ------
            RadioBrowserError: The API did not register the click.

        """
        click_data = await self._request(f"url/{quote(uuid, safe='')}")
        with unexpected_response():
            click = orjson.loads(click_data)  # pylint: disable=no-member
            # The documentation shows "ok" both as a boolean and as a string.
            registered = click["ok"] in (True, "true")
            message = click.get("message", "")
            url = click["url"] if registered else None

        if url is None:
            msg = f"The Radio Browser API did not register the click: {message}"
            raise RadioBrowserError(msg)

        # The click still counts for the station, but the stream to play is
        # the corrected one, when there is one.
        return self._corrections.get(uuid, {}).get("url", url)

    @probatio(error=RadioBrowserValidationError)
    async def vote(self, *, uuid: str) -> None:
        """Vote for a station.

        Votes are what makes a station rank higher. The API only counts one
        vote per station from the same IP address every 10 minutes.

        Args:
        ----
            uuid: UUID of the station.

        Raises:
        ------
            RadioBrowserError: The API did not accept the vote, for example
                because it came in too soon after the previous one.

        """
        vote_data = await self._request(f"vote/{quote(uuid, safe='')}")
        with unexpected_response():
            vote = orjson.loads(vote_data)  # pylint: disable=no-member
            # The documentation shows "ok" both as a boolean and as a string.
            accepted = vote["ok"] in (True, "true")
            message = vote.get("message", "")

        if not accepted:
            msg = f"The Radio Browser API did not accept the vote: {message}"
            raise RadioBrowserError(msg)

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def countries(  # noqa: PLR0913
        self,
        *,
        name: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: ListOrder = Order.NAME,
        reverse: bool = False,
    ) -> list[Country]:
        """Get list of available countries.

        Args:
        ----
            name: Only the ones whose name contains this, ignoring case.
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
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, or the limit or offset is negative.

        """
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
            for country in list_from_json(countries_data):
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

            # The API can only filter on the code, so filter on the name here,
            # ignoring case and accents the same way the sorting below does.
            if name:
                countries = {
                    code: country
                    for code, country in countries.items()
                    if name_sort_key(name) in name_sort_key(country["name"])
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

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def languages(  # noqa: PLR0913
        self,
        *,
        name: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: ListOrder = Order.NAME,
        reverse: bool = False,
    ) -> list[Language]:
        """Get list of available languages.

        Args:
        ----
            name: Only the ones whose name contains this, ignoring case.
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
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, or the limit or offset is negative.

        """
        languages_data = await self._request(
            name_filter_uri("languages", name),
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )

        with unexpected_response():
            languages = list_from_json(languages_data)
            for language in languages:  # pylint: disable=not-an-iterable
                language["name"] = language["name"].title()

            # pylint: disable-next=not-an-iterable
            return [Language.from_dict(language) for language in languages]

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments, too-many-locals
    async def search(  # noqa: PLR0913
        self,
        *,
        filter_by: Annotated[FilterBy, In(SEARCH_FILTERS)] | None = None,
        filter_term: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: StationOrder = Order.NAME,
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
        bitrate_min: Count = 0,
        bitrate_max: Count = 1000000,
        is_https: bool | None = None,
        has_geo_info: bool | None = None,
        has_extended_info: bool | None = None,
        geo_lat: Annotated[float, Latitude()] | None = None,
        geo_long: Annotated[float, Longitude()] | None = None,
        geo_distance: Annotated[float, NonNegative()] | None = None,
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
            language: Search by language, ignoring case.
            language_exact: Match the language exactly instead of part of
                it. A station with more than one language still matches when
                one of them is this language.
            tag: Search by tag, ignoring case.
            tag_exact: Match the tag exactly instead of part of it, for `tag`
                and every tag in `tag_list`. A station with more tags still
                matches when one of them is this tag.
            tag_list: Only stations that match all of these tags, ignoring
                case. Like `tag`, this matches part of a tag ("blues" also
                finds "blues rock"), unless `tag_exact` is set.
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
            RadioBrowserValidationError: The filter_by value is not
                supported, filter_term is missing, the location for a geo
                search is incomplete or not a valid coordinate, the endpoint
                cannot sort by this order, or a count like the limit or offset
                is negative.

        """
        location_incomplete = (geo_lat is None) != (geo_long is None)
        if location_incomplete or (geo_distance is not None and geo_lat is None):
            msg = "geo_lat and geo_long must be set together, also for geo_distance"
            raise RadioBrowserValidationError(msg)

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
            "language": lowercase(language),
            "languageExact": language_exact,
            "tag": lowercase(tag),
            "tagExact": tag_exact,
            "tagList": ",".join(tag_list).lower() if tag_list else None,
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
            if filter_term is None:
                msg = "filter_by requires a filter_term"
                raise RadioBrowserValidationError(msg)

            if filter_by in LOWERCASE_FILTERS:
                filter_term = filter_term.lower()

            key, flags = SEARCH_FILTERS[filter_by]
            params.update({key: filter_term, **flags})

        stations_data = await self._request(
            "stations/search",
            # yarl rejects None as a query value, so unset filters are left out.
            params={key: value for key, value in params.items() if value is not None},
        )
        return stations_from_json(stations_data, self._corrections)

    @probatio(error=RadioBrowserValidationError)
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

    @probatio(error=RadioBrowserValidationError)
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
        return stations_from_json(stations_data, self._corrections)

    @probatio(error=RadioBrowserValidationError)
    async def stations_by_url(self, *, url: str) -> list[Station]:
        """Get the stations that stream from a URL.

        Useful to find the station behind a saved stream URL. Several
        stations can share a stream, so this can return more than one. The
        API only matches the URL a station was registered with, not the one
        it resolves to after redirects or playlists.

        Args:
        ----
            url: The stream URL the station was registered with, its `url`.
                The URL it resolves to, `url_resolved`, does not match.

        Returns:
        -------
            A list of Station objects.

        """
        stations_data = await self._request("stations/byurl", params={"url": url})
        return stations_from_json(stations_data, self._corrections)

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def stations(  # noqa: PLR0913
        self,
        *,
        filter_by: FilterBy | None = None,
        filter_term: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: StationOrder = Order.NAME,
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
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, the limit or offset is negative, or filter_by is set
                without a filter_term.

        """
        uri = "stations"
        if filter_by is not None:
            # Every by* path needs a term, without one the API answers 404.
            if filter_term is None:
                msg = "filter_by requires a filter_term"
                raise RadioBrowserValidationError(msg)

            # Terms like "#original" or "AC/DC" would otherwise change the URL
            # instead of being part of it.
            if filter_by in LOWERCASE_FILTERS:
                filter_term = filter_term.lower()

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
        return stations_from_json(stations_data, self._corrections)

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def tags(  # noqa: PLR0913
        self,
        *,
        name: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: ListOrder = Order.NAME,
        reverse: bool = False,
    ) -> list[Tag]:
        """Get list of available tags.

        Args:
        ----
            name: Only the ones whose name contains this, ignoring case.
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
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, or the limit or offset is negative.

        """
        tags_data = await self._request(
            name_filter_uri("tags", name),
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )
        with unexpected_response():
            tags = list_from_json(tags_data)
            # pylint: disable-next=not-an-iterable
            return [Tag.from_dict(tag) for tag in tags]

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def codecs(  # noqa: PLR0913
        self,
        *,
        name: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: ListOrder = Order.NAME,
        reverse: bool = False,
    ) -> list[Codec]:
        """Get list of codecs the stations stream in.

        Args:
        ----
            name: Only the ones whose name contains this, ignoring case.
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of Codec objects.

        Raises:
        ------
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, or the limit or offset is negative.

        """
        codecs_data = await self._request(
            name_filter_uri("codecs", name),
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )
        with unexpected_response():
            codecs = list_from_json(codecs_data)
            # pylint: disable-next=not-an-iterable
            return [Codec.from_dict(codec) for codec in codecs]

    @probatio(error=RadioBrowserValidationError)
    # pylint: disable-next=too-many-arguments
    async def states(  # noqa: PLR0913
        self,
        *,
        country_code: str | None = None,
        name: str | None = None,
        hide_broken: bool = False,
        limit: Count = 100000,
        offset: Count = 0,
        order: ListOrder = Order.NAME,
        reverse: bool = False,
    ) -> list[State]:
        """Get list of states, provinces and regions the stations are in.

        Args:
        ----
            country_code: Only the states in the country with this ISO 3166-1
                alpha-2 code, like "NL".
            name: Only the ones whose name contains this, ignoring case.
            hide_broken: Do not count broken stations.
            limit: Limit the number of results.
            offset: Offset the results.
            order: Order the results.
            reverse: Reverse the order of the results.

        Returns:
        -------
            A list of State objects.

        Raises:
        ------
            RadioBrowserValidationError: The endpoint cannot sort by this
                order, or the limit or offset is negative.

        """
        # The API filters states on its own name for a country, like "The
        # Netherlands", which is neither the code nor the name countries()
        # returns. Look that name up, so callers can use the country code.
        country = None
        if country_code:
            country = await self._api_country_name(country_code)
            if not country:
                return []

        # The country comes before the name filter in the path. A country
        # without a name filter needs the trailing slash, or the API takes
        # the country for a name filter.
        uri = "states"
        if country:
            uri = f"{uri}/{quote(country, safe='')}/{quote(name or '', safe='')}"
        elif name:
            uri = f"{uri}/{quote(name, safe='')}"

        states_data = await self._request(
            uri,
            params={
                "hidebroken": hide_broken,
                "offset": offset,
                "order": order.value,
                "reverse": reverse,
                "limit": limit,
            },
        )
        with unexpected_response():
            states = list_from_json(states_data)
            # pylint: disable-next=not-an-iterable
            return [State.from_dict(state) for state in states]

    async def _api_country_name(self, country_code: str) -> str | None:
        """Look up the name the API itself uses for a country.

        Args:
        ----
            country_code: The ISO 3166-1 alpha-2 code of the country.

        Returns:
        -------
            The name of the country in the API, or None for an unknown code.
            The API lists some codes without a name, like "XX"; those count
            as unknown too.

        """
        # Concurrent first calls wait for one lookup, instead of each doing
        # their own.
        async with self._api_country_names_lock:
            if self._api_country_names is None:
                countries_data = await self._request("countries")
                with unexpected_response():
                    countries = list_from_json(countries_data)
                    names = {
                        country["iso_3166_1"].upper(): country["name"]
                        # pylint: disable-next=not-an-iterable
                        for country in countries
                    }
                    # These are cached for as long as the client lives, so a
                    # broken one would break every later call too.
                    if not all(isinstance(name, str) for name in names.values()):
                        msg = "Expected the name of every country to be a string"
                        raise TypeError(msg)
                    self._api_country_names = names

        return self._api_country_names.get(country_code.upper()) or None

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

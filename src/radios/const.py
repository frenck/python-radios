"""Asynchronous Python client for the Radio Browser API."""

from enum import StrEnum


class Order(StrEnum):
    """Enum holding the order types."""

    BITRATE = "bitrate"
    CHANGE_TIMESTAMP = "changetimestamp"
    CLICK_COUNT = "clickcount"
    CLICK_TIMESTAMP = "clicktimestamp"
    CLICK_TREND = "clicktrend"
    CODE = "code"
    CODEC = "codec"
    COUNTRY = "country"
    FAVICON = "favicon"
    HOMEPAGE = "homepage"
    LANGUAGE = "language"
    LAST_CHECK_OK = "lastcheckok"
    LAST_CHECK_TIME = "lastchecktime"
    NAME = "name"
    RANDOM = "random"
    STATE = "state"
    STATION_COUNT = "stationcount"
    TAGS = "tags"
    URL = "url"
    VOTES = "votes"


# The countries, languages and tags lists can only be sorted by name or by
# station count. The API answers anything else with a server error.
LIST_ORDERS = frozenset({Order.NAME, Order.STATION_COUNT})

# Stations can be sorted by most of their attributes, but not by these two:
# the API silently ignores them, so the result would not be sorted at all.
STATION_ORDERS = frozenset(Order) - {Order.CODE, Order.STATION_COUNT}


class FilterBy(StrEnum):
    """Enum holding possible filter by types for radio stations."""

    UUID = "byuuid"
    NAME = "byname"
    NAME_EXACT = "bynameexact"
    CODEC = "bycodec"
    CODEC_EXACT = "bycodecexact"
    COUNTRY = "bycountry"
    COUNTRY_EXACT = "bycountryexact"
    COUNTRY_CODE_EXACT = "bycountrycodeexact"
    STATE = "bystate"
    STATE_EXACT = "bystateexact"
    LANGUAGE = "bylanguage"
    LANGUAGE_EXACT = "bylanguageexact"
    TAG = "bytag"
    TAG_EXACT = "bytagexact"


# The flag that represents a language, as an ISO 3166-1 alpha-2 country code,
# keyed by ISO 639-1 language code. A language code is not a country code:
# "ar" (Arabic) is Argentina and "sv" (Swedish) is El Salvador. Languages
# without one obvious country, like Arabic or Catalan, are left out on
# purpose; no flag beats the wrong one.
LANGUAGE_FLAGS = {
    "az": "az",
    "bg": "bg",
    "bn": "bd",
    "bs": "ba",
    "cs": "cz",
    "da": "dk",
    "de": "de",
    "el": "gr",
    "en": "gb",
    "es": "es",
    "et": "ee",
    "fa": "ir",
    "fi": "fi",
    "fr": "fr",
    "ga": "ie",
    "he": "il",
    "hi": "in",
    "hr": "hr",
    "hu": "hu",
    "hy": "am",
    "id": "id",
    "is": "is",
    "it": "it",
    "ja": "jp",
    "ka": "ge",
    "kk": "kz",
    "ko": "kr",
    "lt": "lt",
    "lv": "lv",
    "mk": "mk",
    "ms": "my",
    "nb": "no",
    "ne": "np",
    "nl": "nl",
    "no": "no",
    "pl": "pl",
    "pt": "pt",
    "ro": "ro",
    "ru": "ru",
    "sk": "sk",
    "sl": "si",
    "sq": "al",
    "sr": "rs",
    "sv": "se",
    "th": "th",
    "tl": "ph",
    "tr": "tr",
    "uk": "ua",
    "ur": "pk",
    "vi": "vn",
    "zh": "cn",
}

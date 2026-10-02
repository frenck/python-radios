# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. This file
follows the [agents.md](https://agents.md) convention. `CLAUDE.md` is a symlink
to this file, so Claude-compatible tooling reads the same guidance.

## What this project is

python-radios is an asynchronous Python client for the
[Radio Browser API][radio-browser], a community-maintained directory of internet
radio and TV stations. It resolves an API server through DNS SRV records, sends
the requests over `aiohttp`, and turns the JSON into typed dataclasses. It is
used by the Radio Browser integration in Home Assistant.

The consumer can pass in its own `aiohttp.ClientSession`. If it does not, the
client creates one and closes it again on `close()` or when the async context
manager exits.

## Project layout

| Path                 | Purpose                                                |
| -------------------- | ------------------------------------------------------ |
| `src/radios/`        | The package                                            |
| `  radio_browser.py` | The `RadioBrowser` client: host lookup, requests       |
| `  models.py`        | mashumaro dataclasses for stations, countries and more |
| `  const.py`         | Enums, supported orders, and language flags            |
| `  exceptions.py`    | `RadioBrowserError` and its connection subclasses      |
| `tests/`             | pytest suite; each test has a one-line docstring       |
| `examples/`          | Runnable example against the live API                  |

## Commands

This is a [Poetry][poetry] project that also uses NodeJS for some checks, with
[prek][prek] running the hooks. Set up and run the gate with:

```bash
npm install
poetry install
poetry run prek run --all-files   # lint, format, type, and test hooks
poetry run pytest                 # just the tests
```

During iteration, running a single tool directly is fine and faster:
`poetry run pytest -k ...`, `poetry run ruff check .`, `poetry run ty check src`.

## Conventions

- The library should never leak a raw exception. Transport problems surface as
  `RadioBrowserConnectionError` (or `RadioBrowserConnectionTimeoutError`), and
  anything else as `RadioBrowserError`. Keep that contract when adding code.
  Invalid arguments, a caller mistake rather than an API failure, raise
  `RadioBrowserValidationError` (a `RadioBrowserError` and a `ValueError`).
  Public methods validate their arguments with
  `@probatio(error=RadioBrowserValidationError)` and `Annotated` validators
  (`Count`, `ListOrder` and `StationOrder` in `radio_browser.py`); rules that
  span several arguments are checked in the body and raise
  `RadioBrowserValidationError` themselves.
- Tests never touch the live API. Mock HTTP with `aioresponses` and keep
  realistic API responses as fixtures under `tests/fixtures`.
- Coverage is enforced at 100% on the package. New code needs tests. Every test
  carries a one-line docstring describing what it verifies.
- Comments explain the why, not the what. Clarity over cleverness, clear names,
  and blank lines between logical steps.

## Writing and voice

English for all public artifacts (commits, PRs, issues). Held to a high bar:
clear, honest, no filler. Avoid:

- AI cheerleading and marketing speak (leverage, synergize, delight).
- Em-dashes and en-dashes anywhere. Use a period, colon, comma, or parentheses;
  hyphen only for compound words. Restructure a sentence rather than reach for one.
- "e.g.", "i.e.", "etc."; write "like", "for example", "such as".
- CAPS for emphasis (use italics); "click" as a verb (use "select").
- "HA"/"HASS"; write "Home Assistant" in full, and never frame it as fragile.
- "master/slave"; use "client/server", "leader/follower", "main/replica".

See [AI_POLICY.md](AI_POLICY.md) for the contribution policy around AI tooling.

## Gotchas

- The API host is not fixed. `_resolve_hosts()` looks up the
  `_api._tcp.radio-browser.info` SRV records and shuffles them into `_hosts`;
  the one in use is `_host`. A connection error clears `_host`, so the retry
  moves on to the next server, and the list is looked up again once it runs
  out. When the SRV lookup fails, `all.api.radio-browser.info` is used. Tests
  set `_host` directly to skip the lookup.
- Boolean query parameters are sent as lowercase `"true"`/`"false"`, because
  that is what the API expects.
- The API returns countries as ISO 3166-1 alpha-2 codes, and lists a few of
  them twice, once in lowercase. `countries()` fetches the whole list, merges
  those, resolves the codes to names with `pycountry` (with a special case for
  Kosovo, `XK`), and sorts and pages locally.
- The API uses names of its own for countries in some places, like "The
  Netherlands" for states. `states()` looks those up from a country code.
- Not every endpoint can sort by every `Order`. `LIST_ORDERS` and
  `STATION_ORDERS` in `const.py` hold what each kind accepts, verified against
  the live API; anything else fails or is silently ignored by the API.
- Path segments built from caller input (filter terms, UUIDs, names) are
  escaped with `quote(..., safe="")`, so they cannot change the URL.
- Several station fields (`tags`, `language`, `languagecodes`) arrive as comma
  separated strings and are split into lists by `CommaSeparatedString`.

## Where to read next

- `README.md`: install, usage, and the development setup.
- `examples/example.py`: the basics in one script, the same example the
  README opens with. The README documents every public method.

[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[radio-browser]: https://www.radio-browser.info

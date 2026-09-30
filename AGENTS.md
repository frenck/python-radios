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
| `  const.py`         | `Order` and `FilterBy` enums                           |
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
  Invalid arguments, a caller mistake rather than an API failure, raise a plain
  `ValueError`.
- Tests never touch the live API. Mock HTTP with `aioresponses` and keep
  realistic API responses as fixtures under `tests/fixtures`.
- New code needs tests. Every test carries a one-line docstring describing what
  it verifies.
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

- The API host is not fixed. `_request` looks up `_api._tcp.radio-browser.info`
  SRV records, picks one at random, and caches it in `_host`. Any connection
  error clears `_host`, so the retry lands on a freshly resolved server. Tests
  set `_host` directly to skip the DNS lookup.
- Boolean query parameters are sent as lowercase `"true"`/`"false"`, because
  that is what the API expects.
- The API returns countries as ISO 3166-1 alpha-2 codes. `countries()` resolves
  them to names with `pycountry` (with a special case for Kosovo, `XK`) and
  re-sorts afterwards when ordering by name.
- Several station fields (`tags`, `language`, `languagecodes`) arrive as comma
  separated strings and are split into lists by `CommaSeparatedString`.

## Where to read next

- `README.md`: install, usage, and the development setup.
- `examples/example.py`: every public method in one script.

[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[radio-browser]: https://www.radio-browser.info

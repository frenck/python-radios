# Contributing

Contributions are welcome. This is a solo-maintained project, so for anything
bigger than a small fix, open an issue first so we can align before you spend
time on it.

Please follow the [code of conduct][code-of-conduct] in all your interactions
with the project.

AI tools are welcome as an aid, but you are responsible for everything you
submit: review and understand it before opening a pull request. Autonomous
agents are not allowed, and unreviewed AI output will be closed. Read the
[AI policy][ai-policy] before contributing.

## Issues and feature requests

Found a bug, a mistake in the documentation, or want a new feature? Open an
issue on the [GitHub repository][github]. Search the existing issues first,
your question may already be answered.

Found a security vulnerability? Do not open a public issue; follow the
[security policy][security] instead.

When reporting a problem with a specific request, include the method you
called and its arguments, and if you can, the raw JSON the Radio Browser API
returned. That makes it easy to turn into a test fixture.

## Correcting station data

The library ships corrections for stations with wrong data in Radio Browser,
like a stream URL that moved, a broken favicon, or a duplicate. They live in
`src/radios/corrections/`, in a folder per country (the lowercase country
code), with a JSON file per broadcaster or topic:

```json
{
  "$schema": "../schema.json",
  "corrections": [
    {
      "stationuuid": "00000000-0000-4000-8000-000000000001",
      "reason": "Example FM moved its stream, see https://example.com/listen",
      "url": "https://stream.example.com/example-fm.mp3"
    },
    {
      "stationuuid": "00000000-0000-4000-8000-000000000002",
      "reason": "Duplicate of Example FM (00000000-0000-4000-8000-000000000001)",
      "delete": true
    }
  ]
}
```

For a real one, see `src/radios/corrections/fr/radio-odyssey.json`.

- `stationuuid` is the UUID of the station, shown on its page on the
  [Radio Browser website][radio-browser].
- `reason` says why, so a reviewer can check it, and so it is clear later
  whether the correction is still needed. Link to the source when there is
  one, like the website of the station.
- A correction either deletes the station with `"delete": true`, or overwrites
  one or more of these fields, with the names and formats of the API: `name`,
  `url`, `homepage`, `favicon`, `tags`, `countrycode`, `state`, `iso_3166_2`,
  `language`, `languagecodes`, `geo_lat` and `geo_long`. Tags and languages are
  comma separated, like `"news,pop"`.
- A station has corrections in one place only.

The format follows the [radio-database][radio-database] repository of Radio
Browser, so a correction can be offered upstream as well. The test suite
validates every file, and `schema.json` lets your editor check it as you type.

## Development

The full setup, dependencies, and check/test commands live in the
[README](../README.md#setting-up-development-environment). In short: this is a
[Poetry][poetry] project that also uses NodeJS for some checks.

```bash
npm install
poetry install
poetry run prek run --all-files   # lint + format + type + test hooks
poetry run pytest                 # just the tests
```

Every change is linted, type-checked, and tested in CI, which must be green
before a pull request can merge. Keep coverage up and match the surrounding
style (clear names, why-comments, no silent failures).

## Pull requests

1. Search for open or closed [pull requests][prs] that relate to yours, so you
   don't duplicate effort.
1. Keep the change focused and describe what it does and why.
1. Make sure tests cover your change and the full check suite passes locally.

[ai-policy]: https://github.com/frenck/python-radios/blob/main/AI_POLICY.md
[code-of-conduct]: https://github.com/frenck/python-radios/blob/main/.github/CODE_OF_CONDUCT.md
[github]: https://github.com/frenck/python-radios/issues
[poetry]: https://python-poetry.org
[prs]: https://github.com/frenck/python-radios/pulls
[radio-browser]: https://www.radio-browser.info
[radio-database]: https://gitlab.com/radiobrowser/radio-database
[security]: https://github.com/frenck/python-radios/blob/main/.github/SECURITY.md

"""Run the bundled examples against a mocked API so they cannot silently rot.

The examples in ``examples/`` are user-facing, and the one in the README is a
copy of them: if the public API changes under them, they should fail here
rather than in someone's terminal.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .conftest import API_URL, load_fixture

if TYPE_CHECKING:
    from types import ModuleType

    import pytest
    from aioresponses import aioresponses

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _load_example(name: str) -> ModuleType:
    """Import an example module by file name, without an examples package."""
    spec = importlib.util.spec_from_file_location(
        f"example_{name}", EXAMPLES_DIR / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_example_runs(
    responses: aioresponses, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test the example lists, searches, and plays a station without error."""
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/bycountrycodeexact/NL\?"),
        status=200,
        body=load_fixture("stations.json"),
    )
    responses.get(
        re.compile(rf"^{re.escape(API_URL)}/stations/search\?"),
        status=200,
        body=load_fixture("stations.json"),
    )
    responses.get(
        f"{API_URL}/url/6c95ccdb-ca0a-4c59-a660-96e56ef2dca9",
        status=200,
        body=load_fixture("station_click.json"),
    )

    await _load_example("example").main()

    output = capsys.readouterr().out
    assert "538 (12 clicks)" in output
    assert "Now playing 538: http://playerservices.streamtheworld.com/" in output


def test_every_example_is_covered() -> None:
    """Test no example script is left unrun by this file."""
    scripts = {path.stem for path in EXAMPLES_DIR.glob("*.py")}

    assert scripts == {"example"}

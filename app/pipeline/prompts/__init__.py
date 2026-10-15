"""Versioned prompt files. Bump the `_vN` suffix (and the constant that names it) when a
prompt changes, so eval reports stay comparable."""

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text()

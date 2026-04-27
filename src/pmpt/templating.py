from __future__ import annotations

import re
from collections.abc import Mapping

VARIABLE_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def find_variables(text: str) -> list[str]:
    """Return unique variable names in first-appearance order."""
    seen: set[str] = set()
    names: list[str] = []

    for match in VARIABLE_RE.finditer(text):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)

    return names


def render_template(text: str, values: Mapping[str, str]) -> str:
    """Replace known variables once, without interpreting replacement text."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return values.get(name, match.group(0))

    return VARIABLE_RE.sub(replace, text)

"""Helpers for mapping SL direction names to the numeric direction codes used by Trafiklab."""

from __future__ import annotations

from typing import Any


def build_direction_map(departures: list[dict[str, Any]]) -> dict[str, str]:
    """Build a name -> SL direction code map from a departures payload."""
    direction_map: dict[str, str] = {}

    for departure in departures:
        if not isinstance(departure, dict):
            continue

        direction_code = departure.get("direction_code")
        direction_name = departure.get("direction")
        if direction_code is None or direction_name is None:
            continue

        direction_map[str(direction_name).strip()] = str(direction_code)

    return direction_map


def resolve_direction_value(selected_value: str, direction_map: dict[str, str]) -> str:
    """Return the SL direction code for the selected named direction."""
    normalized = str(selected_value or "").strip()
    if not normalized:
        return "BOTH"

    key = normalized.strip()
    if key.upper() in {"ALL", "BOTH"}:
        return "BOTH"

    return direction_map.get(key, key)

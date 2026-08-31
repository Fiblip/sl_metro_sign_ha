"""Parser helpers for SL departure API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Departure:
    """Single parsed departure.

    The fields intentionally match the user-facing SL API data needed for a
    station departure list: line number, direction name, display time, and
    timestamp.
    """

    line_number: str
    direction: str
    display_time: str
    timestamp: str


@dataclass(slots=True)
class Deviation:
    """Single parsed deviation entry."""

    message: str
    importance_level: int


@dataclass(slots=True)
class StationDepartures:
    """All parsed departures for a station."""

    site_id: str | int | None
    entry_id: str = ""
    departures: list[Departure] = field(default_factory=list)
    deviations: list[Deviation] = field(default_factory=list)


def _clean_text(value: Any) -> str:
    """Normalize string values from the SL API."""
    if value is None:
        return ""
    return str(value).strip()


def _coerce_importance_level(value: Any) -> int:
    """Parse SL deviation importance level, defaulting to 1."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _extract_deviation_message(raw_deviation: dict[str, Any]) -> str:
    """Extract a human-readable message from a raw deviation object."""
    for key in ("message", "text", "header", "title"):
        value = _clean_text(raw_deviation.get(key))
        if value:
            return value
    return ""


def parse_station_departures(
    payload: dict[str, Any],
    *,
    site_id: str | int | None = None,
    entry_id: str = "",
) -> StationDepartures:
    """Parse the raw SL departure payload into structured Python objects.

    The returned list length matches the number of departure entries returned by
    the API, with each item holding the fields needed by the integration.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected SL response type: {type(payload).__name__}")

    raw_departures = payload.get("departures", [])
    if not isinstance(raw_departures, list):
        raw_departures = []

    parsed_departures: list[Departure] = []
    for departure in raw_departures:
        if not isinstance(departure, dict):
            continue

        line_info = departure.get("line") if isinstance(departure.get("line"), dict) else {}
        line_number = _clean_text(
            line_info.get("designation")
            or line_info.get("name")
            or departure.get("lineNumber")
            or ""
        )
        direction = _clean_text(departure.get("direction"))
        display_time = _clean_text(departure.get("display"))
        timestamp = _clean_text(departure.get("expected"))

        parsed_departures.append(
            Departure(
                line_number=line_number,
                direction=direction,
                display_time=display_time,
                timestamp=timestamp,
            )
        )

    raw_stop_deviations = payload.get("stop_deviations", [])
    if not isinstance(raw_stop_deviations, list):
        raw_stop_deviations = []

    parsed_deviations: list[Deviation] = []
    for raw_deviation in raw_stop_deviations:
        if not isinstance(raw_deviation, dict):
            continue

        message = _extract_deviation_message(raw_deviation)
        if not message:
            continue

        importance_level = _coerce_importance_level(raw_deviation.get("importance_level"))
        parsed_deviations.append(Deviation(message=message, importance_level=importance_level))

    return StationDepartures(
        site_id=site_id,
        entry_id=entry_id,
        departures=parsed_departures,
        deviations=parsed_deviations,
    )


def parse_station_option_values(
    departures: list[dict[str, Any]],
    *,
    transport_order: list[str],
    fallback_directions: list[str] | None = None,
) -> dict[str, list[str]]:
    """Parse departures into transport/line/direction option lists."""
    transports: set[str] = set()
    lines: set[str] = set()
    directions: set[str] = set()

    for departure in departures:
        if not isinstance(departure, dict):
            continue

        line_data = departure.get("line") if isinstance(departure.get("line"), dict) else {}
        if isinstance(line_data, dict):
            mode = line_data.get("transport_mode") or line_data.get("transportMode")
            if mode:
                transports.add(str(mode).upper())

            line_value = line_data.get("designation") or line_data.get("name") or departure.get("lineNumber")
            if line_value is not None:
                lines.add(str(line_value))

        direction = departure.get("direction")
        if direction:
            directions.add(str(direction).strip())

    if not transports:
        transports = set(transport_order)

    if not directions and fallback_directions:
        directions = set(fallback_directions)

    transport_rank = {value: index for index, value in enumerate(transport_order)}

    def _sort_numeric(values: set[str]) -> list[str]:
        def _key(item: str) -> tuple[int, str]:
            try:
                return (0, str(int(item)))
            except ValueError:
                return (1, item)

        return sorted(values, key=_key)

    return {
        "transport": sorted(transports, key=lambda value: transport_rank.get(value, len(transport_order))),
        "line": _sort_numeric(lines),
        "direction": sorted(directions, key=lambda value: value.casefold()),
    }
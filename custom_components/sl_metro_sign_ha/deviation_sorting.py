"""Sorting helpers for deviations across all station entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .sl_api_parser import Deviation, StationDepartures


@dataclass(slots=True)
class DeviationSorter:
    """Build one descending list of deviations from all stations."""

    minimum_importance_level: int
    maximum_deviations: int

    def sort_deviations(
        self,
        station_departures: Iterable[StationDepartures],
        *,
        allowed_entry_ids: set[str] | None = None,
    ) -> list[Deviation]:
        """Return de-duplicated deviations sorted by importance level descending."""
        if self.maximum_deviations <= 0:
            return []

        unique_by_message: dict[str, Deviation] = {}
        for station_data in station_departures:
            if allowed_entry_ids is not None and station_data.entry_id not in allowed_entry_ids:
                continue

            for deviation in station_data.deviations:
                message_key = deviation.message.strip().casefold()
                if not message_key:
                    continue

                existing = unique_by_message.get(message_key)
                if existing is None or deviation.importance_level > existing.importance_level:
                    unique_by_message[message_key] = deviation

        filtered = [
            deviation
            for deviation in unique_by_message.values()
            if deviation.importance_level >= self.minimum_importance_level
        ]

        filtered.sort(key=lambda deviation: deviation.importance_level, reverse=True)
        return filtered[: self.maximum_deviations]

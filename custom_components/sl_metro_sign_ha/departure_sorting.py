"""Sorting helpers for departures across all station entries."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime
from typing import Iterable

from .sl_api_parser import Departure, StationDepartures

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DepartureSorter:
    """Build one ascending list of departures from all stations.

    The sorter returns original Departure object references (no deep copy)
    and skips departures that do not have a timestamp.
    """

    max_sorted_entries: int
    minimum_priority_entries: int
    priority_entry_id: str

    def sort_departures(self, station_departures: Iterable[StationDepartures]) -> list[Departure]:
        """Return departures sorted by timestamp ascending, then direction alphabetically on ties."""
        records = self._collect_departure_records(station_departures)
        if not records:
            return []

        sorted_records = sorted(records, key=lambda record: record.sort_key)
        selected_records = sorted_records[: self.max_sorted_entries]
        selected_records = self._enforce_priority_minimum(selected_records, sorted_records)
        final_records = sorted(selected_records, key=lambda record: record.sort_key)
        return [record.departure for record in final_records]

    def _collect_departure_records(self, station_departures: Iterable[StationDepartures]) -> list[_DepartureRecord]:
        """Flatten all station departures and drop items without a valid timestamp."""
        combined: list[_DepartureRecord] = []
        for station_data in station_departures:
            for departure in station_data.departures:
                if not departure.timestamp.strip():
                    _LOGGER.error(
                        "Skipping departure with empty timestamp for site %s: %s",
                        station_data.site_id,
                        departure,
                    )
                    continue

                try:
                    datetime.fromisoformat(departure.timestamp)
                except ValueError:
                    _LOGGER.error(
                        "Skipping departure with corrupt timestamp '%s' for site %s",
                        departure.timestamp,
                        station_data.site_id,
                    )
                    continue

                combined.append(
                    _DepartureRecord(
                        departure=departure,
                        is_priority=(
                            bool(self.priority_entry_id)
                            and station_data.entry_id == self.priority_entry_id
                        ),
                        sort_key=(departure.timestamp, departure.direction.casefold()),
                    )
                )
        return combined

    def _enforce_priority_minimum(
        self,
        selected_records: list[_DepartureRecord],
        all_records: list[_DepartureRecord],
    ) -> list[_DepartureRecord]:
        """Guarantee the configured minimum number of priority departures when possible."""
        if not self.priority_entry_id or self.minimum_priority_entries <= 0:
            return selected_records

        current_priority_count = sum(1 for record in selected_records if record.is_priority)
        if current_priority_count >= self.minimum_priority_entries:
            return selected_records

        needed = self.minimum_priority_entries - current_priority_count
        priority_replacements = [record for record in all_records[self.max_sorted_entries :] if record.is_priority]

        while needed > 0 and priority_replacements:
            non_priority_indices = [index for index, record in enumerate(selected_records) if not record.is_priority]
            if not non_priority_indices:
                break

            remove_index = non_priority_indices[-1]
            selected_records[remove_index] = priority_replacements.pop(0)
            needed -= 1

        return selected_records


@dataclass(slots=True)
class _DepartureRecord:
    """Internal sorting record that keeps departure references intact."""

    departure: Departure
    is_priority: bool
    sort_key: tuple[str, str]

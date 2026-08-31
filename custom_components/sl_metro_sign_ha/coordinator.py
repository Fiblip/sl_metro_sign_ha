"""Data fetching for the SL Metro Sign integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientResponseError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .sl_api_parser import StationDepartures, parse_station_departures

_LOGGER = logging.getLogger(__name__)


class SLDataCoordinator:
    """Fetch and retain SL departures data for one station."""

    def __init__(
        self,
        hass: Any,
        *,
        site_id: int | str | None = None,
        entry_id: str = "",
        transport: str | None = None,
        line: int | str | None = None,
        direction: int | str | None = None,
        forecast: int = 60,
    ) -> None:
        self.hass = hass
        self.site_id = "" if site_id is None else str(site_id)
        self.entry_id = str(entry_id)
        self.transport = "" if transport is None else str(transport).upper()
        self.line = "" if line is None else str(line)
        self.direction = "" if direction is None else str(direction)
        self.forecast = int(forecast)
        self.data: StationDepartures | None = None
        self._refresh_lock = asyncio.Lock()

    async def async_refresh(self) -> StationDepartures:
        """Fetch departures from the SL API and store the parsed departure model."""
        async with self._refresh_lock:
            try:
                _LOGGER.info(
                    "Requesting SL departures for site %s with transport=%s, line=%s, direction=%s, forecast=%s",
                    self.site_id,
                    self.transport,
                    self.line,
                    self.direction,
                    self.forecast,
                )
                payload = await self.async_fetch_departures()
                self.data = parse_station_departures(payload, site_id=self.site_id, entry_id=self.entry_id)
                departures = self.data.departures

                if departures:
                    preview = []
                    for departure in departures[:3]:
                        preview.append({
                            "line": departure.line_number,
                            "direction": departure.direction,
                            "display": departure.display_time,
                            "expected": departure.timestamp,
                        })
                    _LOGGER.info(
                        "SL API received for site %s: departure_count=%s, preview=%s",
                        self.site_id,
                        len(departures),
                        json.dumps(preview, ensure_ascii=False),
                    )
                else:
                    _LOGGER.info("SL API received for site %s: departure_count=0", self.site_id)

                _LOGGER.info(
                    "Parsed departure object for site %s: %s",
                    self.site_id,
                    self.data,
                )

                return self.data
            except ClientResponseError as err:
                if err.status == 429:
                    _LOGGER.warning(
                        "SL API rate limit reached for site %s. Waiting 60 seconds before retrying.",
                        self.site_id,
                    )
                    await asyncio.sleep(60)
                    return self.data or StationDepartures(site_id=self.site_id, entry_id=self.entry_id, departures=[])
                _LOGGER.exception("Failed to fetch SL departures for site %s", self.site_id)
                raise
            except Exception:  # pragma: no cover - logging only
                _LOGGER.exception("Failed to fetch SL departures for site %s", self.site_id)
                raise

    async def async_fetch_departures(self) -> dict[str, Any]:
        """Make the SL departures request using aiohttp."""
        url = f"https://transport.integration.sl.se/v1/sites/{self.site_id}/departures"
        params: dict[str, Any] = {"forecast": self.forecast}

        for key, value in (
            ("transport", self.transport),
            ("line", self.line),
            ("direction", self.direction),
        ):
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized.upper() in {"ALL", "BOTH"}:
                continue
            if key == "direction":
                if normalized.isdigit():
                    params[key] = normalized
                else:
                    _LOGGER.warning(
                        "Ignoring invalid direction value '%s' for site %s. Direction must be an SL numeric code.",
                        normalized,
                        self.site_id,
                    )
                    continue
            else:
                params[key] = normalized.upper()

        session = async_get_clientsession(self.hass)
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()

        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected SL response type: {type(payload).__name__}")

        return payload

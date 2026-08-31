"""Config flow for the SL Metro Sign integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    DEFAULT_ENABLE_DEVIATIONS,
    DEFAULT_FORECAST,
    DEFAULT_MAX_DEVIATIONS,
    DEFAULT_MAX_SORTED_ENTRIES,
    DEFAULT_MIN_DEVIATION_IMPORTANCE,
    DEFAULT_MIN_PRIORITY_ENTRIES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_STATION_ENTRIES,
    MIN_SCAN_INTERVAL_SECONDS,
)
from .direction_mapping import build_direction_map, resolve_direction_value
from .sl_api_parser import parse_station_option_values

TRANSPORT_OPTIONS = [
    "METRO",
    "BUS",
    "TRAM",
    "TRAIN",
    "FERRY",
    "SHIP",
    "TAXI",
]


def _transport_label(value: str) -> str:
    """Render transport labels with initial uppercase only."""
    return value[:1].upper() + value[1:].lower()


def _build_entry_title(station_name: str, line: str, destination: str) -> str:
    """Build the integration entry title shown in Home Assistant UI."""
    clean_station = (station_name or "").strip() or "Unknown"
    clean_line = (line or "").strip() or "?"
    clean_destination = (destination or "").strip() or "Both"
    return f"{clean_station} - {clean_line} {clean_destination}"


class _SLFlowCommon:
    """Shared station/transport/line/direction flow logic."""

    def _use_form_defaults(self) -> bool:
        """Only prefill values when editing an existing config entry."""
        return hasattr(self, "_config_entry")

    def _station_entry_count(self) -> int:
        """Count configured station entries in Home Assistant."""
        count = 0
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = {**entry.data, **entry.options}
            if "site_id" in data:
                count += 1
        return count

    def _has_station_entries(self) -> bool:
        """Return whether at least one station entry exists."""
        return self._station_entry_count() > 0

    def _normalize_priority_state(self) -> None:
        """Keep global priority settings internally consistent."""
        if self._minimum_priority_entries <= 0:
            self._minimum_priority_entries = 0
            self._priority_entry_id = ""

    def _priority_entry_options(self) -> list[selector.SelectOptionDict]:
        """Build selectable station entry options for global priority departure selection."""
        options: list[selector.SelectOptionDict] = []

        if not self._has_station_entries():
            return options

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = {**entry.data, **entry.options}
            site_id = data.get("site_id")
            if site_id is None:
                continue

            entry_title = str(entry.title or data.get("station_name") or f"Station {site_id}")
            options.append(selector.SelectOptionDict(value=entry.entry_id, label=entry_title))

        return options

    def _api_settings_schema(self) -> vol.Schema:
        """Build the global API settings step schema."""
        return vol.Schema(
            {
                vol.Required("forecast", default=self._forecast): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=180,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("scan_interval_seconds", default=self._scan_interval_seconds): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_SECONDS,
                        max=3600,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    def _departures_settings_schema(self) -> vol.Schema:
        """Build the global departures settings step schema."""
        return vol.Schema(
            {
                vol.Required("maximum_sorted_entries", default=self._maximum_sorted_entries): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=10,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("minimum_priority_entries", default=self._minimum_priority_entries): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=10,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    def _deviations_settings_schema(self) -> vol.Schema:
        """Build the global deviations settings step schema."""
        return vol.Schema(
            {
                vol.Required("deviations_enabled", default=self._deviations_enabled): bool,
                vol.Required("maximum_deviations", default=self._maximum_deviations): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=5,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("minimum_deviation_importance", default=self._minimum_deviation_importance): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=100,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    def _global_settings_schema(self) -> vol.Schema:
        """Compatibility alias for older calls."""
        return self._api_settings_schema()

    def _priority_settings_schema(self) -> vol.Schema:
        """Build the dedicated priority selection step schema."""
        return vol.Schema(
            {
                vol.Required("priority_entry_id", default=self._priority_entry_id): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._priority_entry_options(),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=False,
                    )
                ),
            }
        )

    def _collect_global_departure_settings(self, user_input: dict[str, Any]) -> None:
        """Apply global departures settings from form input."""
        self._maximum_sorted_entries = int(user_input["maximum_sorted_entries"])
        self._minimum_priority_entries = int(user_input.get("minimum_priority_entries", self._minimum_priority_entries))
        self._normalize_priority_state()

    def _validate_global_departure_settings(self) -> str | None:
        """Validate global departures settings and return an error key when invalid."""
        if not self._has_station_entries() and self._minimum_priority_entries > 0:
            return "priority_entries_require_station"
        if self._minimum_priority_entries > self._maximum_sorted_entries:
            return "invalid_priority_configuration"
        return None

    def _collect_global_deviations_settings(self, user_input: dict[str, Any]) -> None:
        """Apply global deviations settings from form input."""
        self._deviations_enabled = bool(user_input.get("deviations_enabled", self._deviations_enabled))
        self._maximum_deviations = int(user_input.get("maximum_deviations", self._maximum_deviations))
        self._minimum_deviation_importance = int(
            user_input.get("minimum_deviation_importance", self._minimum_deviation_importance)
        )

    def _validate_global_deviations_settings(self) -> str | None:
        """Validate global deviations settings and return an error key when invalid."""
        if self._maximum_deviations < 0 or self._maximum_deviations > 5:
            return "invalid_deviation_configuration"
        if self._minimum_deviation_importance <= 0 or self._minimum_deviation_importance > 100:
            return "invalid_deviation_configuration"
        return None

    def _must_select_priority_departure(self) -> bool:
        """Return whether a priority departure selection step is required."""
        return self._minimum_priority_entries > 0

    def _global_settings_payload(self) -> dict[str, Any]:
        """Build the global settings payload for create/update operations."""
        return {
            "forecast": self._forecast,
            "scan_interval_seconds": self._scan_interval_seconds,
            "maximum_sorted_entries": self._maximum_sorted_entries,
            "minimum_priority_entries": self._minimum_priority_entries,
            "priority_entry_id": self._priority_entry_id,
            "deviations_enabled": self._deviations_enabled,
            "maximum_deviations": self._maximum_deviations,
            "minimum_deviation_importance": self._minimum_deviation_importance,
        }

    def _init_flow_state(self, initial: dict[str, Any] | None = None) -> None:
        data = initial or {}
        self._station_matches: list[dict[str, Any]] = []
        self._direction_map: dict[str, str] = {}
        self._site_id: int | None = int(data["site_id"]) if data.get("site_id") is not None else None
        self._station_name: str = str(data.get("station_name") or "")
        self._transport: str = str(data.get("transport") or "").upper()
        self._line: str = str(data.get("line") or "")
        self._direction_code: str = str(data.get("direction") or "")
        self._direction_name: str = str(data.get("direction_name") or "")
        self._forecast: int = int(data.get("forecast") or DEFAULT_FORECAST)
        self._scan_interval_seconds: int = int(data.get("scan_interval_seconds") or DEFAULT_SCAN_INTERVAL_SECONDS)
        self._maximum_sorted_entries: int = int(data.get("maximum_sorted_entries") or DEFAULT_MAX_SORTED_ENTRIES)
        self._minimum_priority_entries: int = int(data.get("minimum_priority_entries") or DEFAULT_MIN_PRIORITY_ENTRIES)
        self._priority_entry_id: str = str(data.get("priority_entry_id") or "")
        self._deviations_enabled: bool = bool(data.get("deviations_enabled", DEFAULT_ENABLE_DEVIATIONS))
        self._maximum_deviations: int = int(data.get("maximum_deviations") or DEFAULT_MAX_DEVIATIONS)
        self._minimum_deviation_importance: int = int(
            data.get("minimum_deviation_importance") or DEFAULT_MIN_DEVIATION_IMPORTANCE
        )

    async def _async_search_stations(self, hass: HomeAssistant, station_name: str) -> list[dict[str, Any]]:
        """Search for stations by name using the SL Trafiklab stop lookup API."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        query = (station_name or "").strip()
        if not query:
            return []

        api_url = "https://transport.integration.sl.se/v1/sites"
        websession = async_get_clientsession(hass)
        try:
            async with websession.get(api_url, params={"query": query}, timeout=15) as response:
                response.raise_for_status()
                payload = await response.json()
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        target_lower = query.casefold()
        matches: list[tuple[int, int, dict[str, Any]]] = []

        for station in payload:
            if not isinstance(station, dict):
                continue

            site_id = station.get("id")
            name = str(station.get("name") or "").strip()
            if site_id is None or not name:
                continue

            name_lower = name.casefold()
            if target_lower in name_lower:
                if name_lower == target_lower:
                    score = 100
                elif name_lower.startswith(target_lower):
                    score = 90
                else:
                    score = 80

                matches.append((score, len(name), {"id": int(site_id), "name": name}))

        if not matches:
            return []

        matches.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in matches[:20]]

    async def _async_fetch_station_departures(
        self,
        site_id: int,
        *,
        transport: str | None = None,
        line: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch departure data for a station using a 2-hour forecast window."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        params: dict[str, Any] = {"forecast": 120}
        if transport:
            params["transport"] = str(transport).upper()
        if line:
            params["line"] = str(line)

        api_url = f"https://transport.integration.sl.se/v1/sites/{site_id}/departures"
        websession = async_get_clientsession(self.hass)
        try:
            async with websession.get(api_url, params=params, timeout=15) as response:
                response.raise_for_status()
                payload = await response.json()
        except Exception:
            return []

        if not isinstance(payload, dict):
            return []

        departures = payload.get("departures", [])
        return departures if isinstance(departures, list) else []

    async def _async_fetch_station_options(
        self,
        site_id: int,
        *,
        transport: str | None = None,
        line: str | None = None,
    ) -> dict[str, list[str]]:
        """Build valid dropdown options for current selections."""
        departures = await self._async_fetch_station_departures(site_id, transport=transport, line=line)

        self._direction_map = build_direction_map(departures)
        fallback_directions = list(self._direction_map.keys())
        if not fallback_directions and self._direction_name:
            fallback_directions = [self._direction_name]

        return parse_station_option_values(
            departures,
            transport_order=TRANSPORT_OPTIONS,
            fallback_directions=fallback_directions,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: Global settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._forecast = int(user_input["forecast"])
                self._scan_interval_seconds = int(user_input["scan_interval_seconds"])
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                return await self.async_step_station_search()

        return self.async_show_form(
            step_id="user",
            data_schema=self._global_settings_schema(),
            errors=errors,
        )

    async def async_step_station_search(self, user_input: dict[str, Any] | None = None):
        """Step 2: Search for station."""
        errors: dict[str, str] = {}

        if user_input is not None:
            station_name = str(user_input["station_name"]).strip()
            if not station_name:
                errors["base"] = "invalid_station"
            else:
                matches = await self._async_search_stations(self.hass, station_name)
                if not matches:
                    errors["base"] = "no_station_found"
                else:
                    self._station_name = station_name
                    self._station_matches = matches
                    return await self.async_step_station()

        return self.async_show_form(
            step_id="station_search",
            data_schema=vol.Schema(
                {
                    (
                        vol.Required("station_name", default=self._station_name)
                        if self._use_form_defaults()
                        else vol.Required("station_name")
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_station(self, user_input: dict[str, Any] | None = None):
        """Step 3: Select station."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_site_id = int(user_input["station"])
            for station in self._station_matches:
                if station["id"] == selected_site_id:
                    self._site_id = selected_site_id
                    self._station_name = station["name"]
                    self._direction_name = ""
                    self._direction_code = ""
                    return await self.async_step_transport()
            errors["base"] = "invalid_station"

        options = [
            selector.SelectOptionDict(value=str(station["id"]), label=station["name"])
            for station in self._station_matches
        ]

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required("station"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_transport(self, user_input: dict[str, Any] | None = None):
        """Step 4: Select mode."""
        if self._site_id is None:
            return self.async_abort(reason="no_station_selected")

        station_options = await self._async_fetch_station_options(self._site_id)
        transport_values = station_options.get("transport", [])

        if user_input is not None:
            self._transport = str(user_input["transport"]).upper()
            return await self.async_step_line()

        return self.async_show_form(
            step_id="transport",
            data_schema=vol.Schema(
                {
                    (
                        vol.Required("transport", default=self._transport)
                        if self._use_form_defaults()
                        else vol.Required("transport")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=value, label=_transport_label(value))
                                for value in transport_values
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                        )
                    ),
                }
            ),
        )

    async def async_step_line(self, user_input: dict[str, Any] | None = None):
        """Step 5: Select line."""
        if self._site_id is None:
            return self.async_abort(reason="no_station_selected")

        station_options = await self._async_fetch_station_options(self._site_id, transport=self._transport)
        line_values = station_options.get("line", [])

        if not line_values:
            return self.async_abort(reason="no_line_found")

        if self._line not in line_values and self._use_form_defaults():
            self._line = line_values[0]

        if user_input is not None:
            self._line = str(user_input["line"])
            return await self.async_step_direction()

        return self.async_show_form(
            step_id="line",
            data_schema=vol.Schema(
                {
                    (
                        vol.Required("line", default=self._line)
                        if self._use_form_defaults()
                        else vol.Required("line")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[selector.SelectOptionDict(value=value, label=value) for value in line_values],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                        )
                    ),
                }
            ),
        )

    async def async_step_direction(self, user_input: dict[str, Any] | None = None):
        """Step 6: Select destination."""
        if self._site_id is None:
            return self.async_abort(reason="no_station_selected")

        station_options = await self._async_fetch_station_options(self._site_id, transport=self._transport, line=self._line)
        direction_values = station_options.get("direction", [])
        if not direction_values:
            return self.async_abort(reason="no_direction_found")

        if self._direction_name not in direction_values and self._use_form_defaults():
            self._direction_name = direction_values[0]

        if user_input is not None:
            selected_direction = str(user_input["direction"]).strip()
            direction_code = resolve_direction_value(selected_direction, self._direction_map)
            if not direction_code.isdigit():
                return self.async_show_form(
                    step_id="direction",
                    data_schema=vol.Schema(
                        {
                            (
                                vol.Required("direction", default=self._direction_name)
                                if self._use_form_defaults()
                                else vol.Required("direction")
                            ): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=[selector.SelectOptionDict(value=value, label=value) for value in direction_values],
                                    mode=selector.SelectSelectorMode.DROPDOWN,
                                    multiple=False,
                                )
                            ),
                        }
                    ),
                    errors={"base": "invalid_direction"},
                )

            self._direction_name = selected_direction
            self._direction_code = direction_code
            return await self._async_finish_flow()

        return self.async_show_form(
            step_id="direction",
            data_schema=vol.Schema(
                {
                    (
                        vol.Required("direction", default=self._direction_name)
                        if self._use_form_defaults()
                        else vol.Required("direction")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[selector.SelectOptionDict(value=value, label=value) for value in direction_values],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                        )
                    ),
                }
            ),
        )

class SLMqttConfigFlow(_SLFlowCommon, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SL Metro Sign."""

    VERSION = 1

    def __init__(self) -> None:
        self._init_flow_state()

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow handler for this config entry."""
        return SLMqttOptionsFlow(config_entry)

    def _get_global_settings_entry(self) -> config_entries.ConfigEntry | None:
        """Return the config entry used for global settings, if present."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            merged = {**entry.data, **entry.options}
            if "site_id" not in merged:
                return entry
        return None

    def _apply_existing_global_settings(self, entry: config_entries.ConfigEntry | None = None) -> None:
        """Load global settings from the dedicated global settings entry, if available."""
        target_entry = entry or self._get_global_settings_entry()
        if target_entry is None:
            return

        global_data = {**target_entry.data, **target_entry.options}
        self._forecast = int(global_data.get("forecast", self._forecast))
        self._scan_interval_seconds = int(global_data.get("scan_interval_seconds", self._scan_interval_seconds))
        self._maximum_sorted_entries = int(global_data.get("maximum_sorted_entries", self._maximum_sorted_entries))
        self._minimum_priority_entries = int(global_data.get("minimum_priority_entries", self._minimum_priority_entries))
        self._priority_entry_id = str(global_data.get("priority_entry_id") or self._priority_entry_id)
        self._deviations_enabled = bool(global_data.get("deviations_enabled", self._deviations_enabled))
        self._maximum_deviations = int(global_data.get("maximum_deviations", self._maximum_deviations))
        self._minimum_deviation_importance = int(
            global_data.get("minimum_deviation_importance", self._minimum_deviation_importance)
        )
        self._normalize_priority_state()

    def _create_global_settings_entry(self):
        """Persist the dedicated global settings entry."""
        return self.async_create_entry(
            title="SL Metro Sign Settings",
            data=self._global_settings_payload(),
        )

    def _station_entry_limit_reached(self) -> bool:
        """Return whether the configured station entry cap has been reached."""
        return self._station_entry_count() >= MAX_STATION_ENTRIES

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1 for global flow: API settings."""
        global_entry = self._get_global_settings_entry()
        if global_entry is not None:
            self._apply_existing_global_settings(global_entry)
            if self._station_entry_limit_reached():
                return self.async_abort(reason="max_station_entries_reached")
            return await self.async_step_station_search()

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._forecast = int(user_input["forecast"])
                self._scan_interval_seconds = int(user_input["scan_interval_seconds"])
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                return await self.async_step_departures()

        return self.async_show_form(
            step_id="user",
            data_schema=self._api_settings_schema(),
            errors=errors,
        )

    async def async_step_departures(self, user_input: dict[str, Any] | None = None):
        """Step 2 for global flow: departures settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._collect_global_departure_settings(user_input)
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                validation_error = self._validate_global_departure_settings()
                if validation_error:
                    errors["base"] = validation_error
                elif self._must_select_priority_departure():
                    self._priority_entry_id = ""
                    return await self.async_step_priority_departure()
                else:
                    self._priority_entry_id = ""
                    return await self.async_step_deviations()

        return self.async_show_form(
            step_id="departures",
            data_schema=self._departures_settings_schema(),
            errors=errors,
        )

    async def async_step_priority_departure(self, user_input: dict[str, Any] | None = None):
        """Collect the priority departure after minimum priority count is known."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._priority_entry_id = str(user_input.get("priority_entry_id") or "").strip()
            return await self.async_step_deviations()

        return self.async_show_form(
            step_id="priority_departure",
            data_schema=self._priority_settings_schema(),
            errors=errors,
        )

    async def async_step_deviations(self, user_input: dict[str, Any] | None = None):
        """Step 3/4 for global flow: deviations settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._collect_global_deviations_settings(user_input)
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                validation_error = self._validate_global_deviations_settings()
                if validation_error:
                    errors["base"] = validation_error
                else:
                    return self._create_global_settings_entry()

        return self.async_show_form(
            step_id="deviations",
            data_schema=self._deviations_settings_schema(),
            errors=errors,
        )

    async def _async_finish_flow(self):
        title = _build_entry_title(self._station_name, self._line, self._direction_name)
        return self.async_create_entry(
            title=title,
            data={
                "site_id": self._site_id,
                "station_name": self._station_name,
                "transport": self._transport,
                "line": self._line,
                "direction": self._direction_code,
                "direction_name": self._direction_name,
                "forecast": self._forecast,
                "scan_interval_seconds": self._scan_interval_seconds,
            },
        )


class SLMqttOptionsFlow(_SLFlowCommon, config_entries.OptionsFlow):
    """Reconfigure an existing SL Metro Sign config entry via full wizard."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        merged = {**config_entry.data, **config_entry.options}
        self._init_flow_state(merged)
        self._is_global_settings_entry = "site_id" not in merged

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Start options flow from global or station setup, based on entry type."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1 for options global flow: API settings."""
        if not self._is_global_settings_entry:
            return await self.async_step_station_search(user_input)

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._forecast = int(user_input["forecast"])
                self._scan_interval_seconds = int(user_input["scan_interval_seconds"])
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                return await self.async_step_departures()

        return self.async_show_form(
            step_id="user",
            data_schema=self._api_settings_schema(),
            errors=errors,
        )

    async def async_step_departures(self, user_input: dict[str, Any] | None = None):
        """Step 2 for options global flow: departures settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._collect_global_departure_settings(user_input)
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                validation_error = self._validate_global_departure_settings()
                if validation_error:
                    errors["base"] = validation_error
                elif self._must_select_priority_departure():
                    self._priority_entry_id = str(self._config_entry.data.get("priority_entry_id") or self._priority_entry_id)
                    return await self.async_step_priority_departure()
                else:
                    self._priority_entry_id = ""
                    return await self.async_step_deviations()

        return self.async_show_form(
            step_id="departures",
            data_schema=self._departures_settings_schema(),
            errors=errors,
        )

    def _save_global_settings(self):
        """Persist updated global settings for the current options entry."""
        updated_data = dict(self._config_entry.data)
        updated_data.update(self._global_settings_payload())
        self.hass.config_entries.async_update_entry(self._config_entry, data=updated_data)

        return self.async_create_entry(title="", data={})

    async def async_step_priority_departure(self, user_input: dict[str, Any] | None = None):
        """Collect the priority departure after minimum priority count is known."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._priority_entry_id = str(user_input.get("priority_entry_id") or "").strip()
            return await self.async_step_deviations()

        return self.async_show_form(
            step_id="priority_departure",
            data_schema=self._priority_settings_schema(),
            errors=errors,
        )

    async def async_step_deviations(self, user_input: dict[str, Any] | None = None):
        """Step 3/4 for options global flow: deviations settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._collect_global_deviations_settings(user_input)
            except (TypeError, ValueError):
                errors["base"] = "invalid_input"
            else:
                validation_error = self._validate_global_deviations_settings()
                if validation_error:
                    errors["base"] = validation_error
                else:
                    return self._save_global_settings()

        return self.async_show_form(
            step_id="deviations",
            data_schema=self._deviations_settings_schema(),
            errors=errors,
        )

    async def _async_finish_flow(self):
        new_data = {
            "site_id": self._site_id,
            "station_name": self._station_name,
            "transport": self._transport,
            "line": self._line,
            "direction": self._direction_code,
            "direction_name": self._direction_name,
            "forecast": self._forecast,
            "scan_interval_seconds": self._scan_interval_seconds,
        }
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=new_data,
            title=_build_entry_title(self._station_name, self._line, self._direction_name),
        )
        return self.async_create_entry(title="", data={})

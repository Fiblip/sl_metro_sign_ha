"""Phase 3 implementation for the SL Metro Sign Home Assistant integration."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DEFAULT_ENABLE_DEVIATIONS,
    DEFAULT_FORECAST,
    DEFAULT_MAX_DEVIATIONS,
    DEFAULT_MAX_SORTED_ENTRIES,
    DEFAULT_MIN_DEVIATION_IMPORTANCE,
    DEFAULT_MIN_PRIORITY_ENTRIES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    MQTT_DEPARTURES_TOPIC,
    MQTT_DEVIATIONS_TOPIC,
)
from .coordinator import SLDataCoordinator
from .deviation_sorting import DeviationSorter
from .departure_sorting import DepartureSorter
from .mqtt_builder import (
    async_publish_departures_json,
    async_publish_deviations_json,
    build_departures_payload_json,
    build_deviations_payload_json,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.LIGHT]


def is_display_enabled(hass: HomeAssistant) -> bool:
    """Return whether the metro sign display is currently enabled."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "display_enabled" in domain_data:
        return bool(domain_data["display_enabled"])
    return _get_global_settings_entry(hass) is None


def _get_global_settings_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the dedicated global settings entry, if present."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        data = {**entry.data, **entry.options}
        if "site_id" not in data:
            return entry
    return None


def _get_global_scan_interval_seconds(hass: HomeAssistant) -> int:
    """Read the shared refresh interval from the global settings entry."""
    global_entry = _get_global_settings_entry(hass)
    if global_entry is None:
        return max(MIN_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL_SECONDS)

    data = {**global_entry.data, **global_entry.options}
    return max(MIN_SCAN_INTERVAL_SECONDS, int(data.get("scan_interval_seconds", DEFAULT_SCAN_INTERVAL_SECONDS)))


def _get_global_sort_limits(hass: HomeAssistant) -> tuple[int, int]:
    """Read the shared sorted-list limits from the global settings entry."""
    global_entry = _get_global_settings_entry(hass)
    if global_entry is None:
        return DEFAULT_MAX_SORTED_ENTRIES, DEFAULT_MIN_PRIORITY_ENTRIES

    data = {**global_entry.data, **global_entry.options}
    return (
        int(data.get("maximum_sorted_entries", DEFAULT_MAX_SORTED_ENTRIES)),
        int(data.get("minimum_priority_entries", DEFAULT_MIN_PRIORITY_ENTRIES)),
    )


def _get_global_priority_entry_id(hass: HomeAssistant) -> str:
    """Read the globally selected priority entry id."""
    global_entry = _get_global_settings_entry(hass)
    if global_entry is None:
        return ""

    data = {**global_entry.data, **global_entry.options}
    return str(data.get("priority_entry_id") or "").strip()


def _get_global_deviation_settings(hass: HomeAssistant) -> tuple[bool, int, int]:
    """Read global deviations settings (enabled, max count, min importance)."""
    global_entry = _get_global_settings_entry(hass)
    if global_entry is None:
        return DEFAULT_ENABLE_DEVIATIONS, DEFAULT_MAX_DEVIATIONS, DEFAULT_MIN_DEVIATION_IMPORTANCE

    data = {**global_entry.data, **global_entry.options}
    return (
        bool(data.get("deviations_enabled", DEFAULT_ENABLE_DEVIATIONS)),
        int(data.get("maximum_deviations", DEFAULT_MAX_DEVIATIONS)),
        int(data.get("minimum_deviation_importance", DEFAULT_MIN_DEVIATION_IMPORTANCE)),
    )


async def _async_refresh_all_station_entries(hass: HomeAssistant) -> None:
    """Refresh every real station entry once using the shared global timer."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    coordinators = domain_data.get("coordinators", [])
    if not coordinators:
        return

    station_departure_objects = []
    for coordinator in coordinators:
        try:
            station_departures = await coordinator.async_refresh()
            station_departure_objects.append(station_departures)
        except Exception:
            _LOGGER.exception(
                "Failed to refresh station %s during the shared integration timer.",
                getattr(coordinator, "site_id", "unknown"),
            )
            continue

    max_sorted_entries, minimum_priority_entries = _get_global_sort_limits(hass)
    priority_entry_id = _get_global_priority_entry_id(hass)
    sorter = DepartureSorter(
        max_sorted_entries=max_sorted_entries,
        minimum_priority_entries=minimum_priority_entries,
        priority_entry_id=priority_entry_id,
    )
    sorted_departures = sorter.sort_departures(station_departure_objects)
    domain_data["sorted_departures"] = sorted_departures

    included_station_entry_ids: set[str] = set()
    if sorted_departures:
        departures_by_station_entry_id: dict[str, set[int]] = {
            station_data.entry_id: {id(departure) for departure in station_data.departures}
            for station_data in station_departure_objects
        }
        for departure in sorted_departures:
            departure_object_id = id(departure)
            for entry_id, departure_ids in departures_by_station_entry_id.items():
                if departure_object_id in departure_ids:
                    included_station_entry_ids.add(entry_id)
                    break

    try:
        await async_publish_departures_json(hass, build_departures_payload_json(sorted_departures))
    except Exception:
        _LOGGER.exception("Failed to publish departures payload to topic '%s'.", MQTT_DEPARTURES_TOPIC)

    deviations_enabled, maximum_deviations, minimum_deviation_importance = _get_global_deviation_settings(hass)
    if deviations_enabled:
        deviation_sorter = DeviationSorter(
            minimum_importance_level=minimum_deviation_importance,
            maximum_deviations=maximum_deviations,
        )
        sorted_deviations = deviation_sorter.sort_deviations(
            station_departure_objects,
            allowed_entry_ids=included_station_entry_ids,
        )
    else:
        sorted_deviations = []

    domain_data["sorted_deviations"] = sorted_deviations

    try:
        await async_publish_deviations_json(hass, build_deviations_payload_json(sorted_deviations))
    except Exception:
        _LOGGER.exception("Failed to publish deviations payload to topic '%s'.", MQTT_DEVIATIONS_TOPIC)

    ordered_departure_view = [
        {
            "line_number": departure.line_number,
            "direction": departure.direction,
            "display_time": departure.display_time,
            "timestamp": departure.timestamp,
        }
        for departure in sorted_departures
    ]
    _LOGGER.info(
        "Sorted departures across all station entries (%s items): %s",
        len(sorted_departures),
        json.dumps(ordered_departure_view, ensure_ascii=False),
    )


def _cancel_global_refresh_timer(hass: HomeAssistant) -> None:
    """Cancel the shared refresh timer if it exists."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    existing_unsub = domain_data.pop("refresh_unsub", None)
    if existing_unsub is not None:
        existing_unsub()
    domain_data.pop("refresh_interval_seconds", None)


def _ensure_global_refresh_timer(hass: HomeAssistant) -> None:
    """Create exactly one shared timer for all station coordinators."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not is_display_enabled(hass):
        _cancel_global_refresh_timer(hass)
        return

    interval_seconds = _get_global_scan_interval_seconds(hass)

    existing_unsub = domain_data.get("refresh_unsub")
    existing_interval = int(domain_data.get("refresh_interval_seconds", 0))
    if existing_unsub is not None:
        if existing_interval == interval_seconds:
            return
        existing_unsub()
        domain_data.pop("refresh_unsub", None)

    async def _refresh_interval(_now: Any) -> None:
        await _async_refresh_all_station_entries(hass)

    unsub = async_track_time_interval(
        hass,
        _refresh_interval,
        timedelta(seconds=interval_seconds),
    )
    domain_data["refresh_unsub"] = unsub
    domain_data["refresh_interval_seconds"] = interval_seconds


async def async_set_display_enabled(
    hass: HomeAssistant,
    enabled: bool,
    *,
    refresh_immediately: bool = False,
) -> None:
    """Pause or resume station refreshes based on display power state."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    was_enabled = is_display_enabled(hass)
    domain_data["display_enabled"] = enabled

    if not enabled:
        _cancel_global_refresh_timer(hass)
        return

    if refresh_immediately:
        await _async_refresh_all_station_entries(hass)

    if refresh_immediately or not was_enabled:
        _ensure_global_refresh_timer(hass)


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    """Set up the SL Metro Sign integration from YAML config only when explicitly configured."""
    domain_config = config.get(DOMAIN)
    if not domain_config:
        return True

    site_id = domain_config.get("site_id")
    transport = domain_config.get("transport")
    line = domain_config.get("line")
    direction = domain_config.get("direction")
    forecast = domain_config.get("forecast", DEFAULT_FORECAST)

    _LOGGER.info(
        "Initializing SL Metro Sign integration with site_id=%s, transport=%s, line=%s, direction=%s, forecast=%s",
        site_id,
        transport,
        line,
        direction,
        forecast,
    )

    coordinator = SLDataCoordinator(
        hass,
        site_id=site_id,
        entry_id="",
        transport=transport,
        line=line,
        direction=direction,
        forecast=forecast,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinator"] = coordinator

    async def _refresh_interval(_now: Any) -> None:
        await coordinator.async_refresh()

    async_track_time_interval(hass, _refresh_interval, timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS))
    await coordinator.async_refresh()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options/data updates by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration from a config entry."""
    data = {**entry.data, **entry.options}
    scan_interval_seconds = int(data.get("scan_interval_seconds", DEFAULT_SCAN_INTERVAL_SECONDS))

    domain_data = hass.data.setdefault(DOMAIN, {})

    if "site_id" not in data:
        _LOGGER.info(
            "SL Metro Sign integration '%s' configured with global settings only; waiting for station/entity setup.",
            entry.entry_id,
        )
        domain_data.setdefault("display_enabled", False)
        domain_data[entry.entry_id] = {}
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        return True

    _LOGGER.info(
        "Setting up SL Metro Sign config entry: %s with site_id=%s, transport=%s, line=%s, direction=%s, forecast=%s, scan_interval_seconds=%s",
        entry.entry_id,
        data.get("site_id"),
        data.get("transport"),
        data.get("line"),
        data.get("direction"),
        data.get("forecast", DEFAULT_FORECAST),
        scan_interval_seconds,
    )

    coordinator = SLDataCoordinator(
        hass,
        site_id=data.get("site_id"),
        entry_id=entry.entry_id,
        transport=data.get("transport"),
        line=data.get("line"),
        direction=data.get("direction"),
        forecast=data.get("forecast", DEFAULT_FORECAST),
    )

    station_coordinators = domain_data.setdefault("coordinators", [])
    if coordinator not in station_coordinators:
        station_coordinators.append(coordinator)

    domain_data[entry.entry_id] = {"coordinator": coordinator}
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    if is_display_enabled(hass):
        _ensure_global_refresh_timer(hass)
        await _async_refresh_all_station_entries(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SL Metro Sign config entry: %s", entry.entry_id)
    domain_data = hass.data.get(DOMAIN, {})
    entry_state = domain_data.pop(entry.entry_id, None)

    station_coordinators = domain_data.get("coordinators", [])
    if entry_state and isinstance(entry_state, dict) and "coordinator" in entry_state:
        coordinator = entry_state["coordinator"]
        if coordinator in station_coordinators:
            station_coordinators.remove(coordinator)

    if not station_coordinators and "refresh_unsub" in domain_data:
        _cancel_global_refresh_timer(hass)

    data = {**entry.data, **entry.options}
    if "site_id" not in data:
        _cancel_global_refresh_timer(hass)
        domain_data.pop("display_enabled", None)
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return True

"""MQTT payload building and publishing helpers for the SL Metro Sign integration."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.mqtt import async_publish
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MQTT_DEPARTURES_TOPIC, MQTT_DEVIATIONS_TOPIC, MQTT_STATE_TOPIC
from .sl_api_parser import Departure, Deviation

_MQTT_PAYLOAD_CACHE_KEY = "last_published_payloads"


def _serialize_payload(payload: Any) -> str:
    """Serialize MQTT payload values for stable change detection."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (int, float, bool)):
        return str(payload)
    if payload is None:
        return ""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _async_publish_if_changed(
    hass: HomeAssistant,
    topic: str,
    payload: Any,
    *,
    retain: bool = True,
) -> None:
    """Publish to MQTT only when payload differs from the last sent value for topic."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    topic_cache: dict[str, str] = domain_data.setdefault(_MQTT_PAYLOAD_CACHE_KEY, {})
    serialized_payload = _serialize_payload(payload)

    if topic_cache.get(topic) == serialized_payload:
        return

    await async_publish(hass, topic, payload, retain=retain)
    topic_cache[topic] = serialized_payload


def _coerce_dep_num(value: str) -> int | None:
    """Convert line designations to an integer when possible."""
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def build_departures_payload(sorted_departures: list[Departure]) -> dict[str, object]:
    """Build the MQTT payload for the LED sign."""
    dep_info_list = [
        {
            "dep_name": departure.direction or "Uknown",
            "dep_num": _coerce_dep_num(departure.line_number),
            "dep_time": departure.display_time,
        }
        for departure in sorted_departures
    ]
    return {
        "noof_deps": len(dep_info_list),
        "dep_info_list": dep_info_list,
    }


def build_departures_payload_json(sorted_departures: list[Departure]) -> str:
    """Build the serialized MQTT payload for the LED sign."""
    return json.dumps(build_departures_payload(sorted_departures), ensure_ascii=False)


async def async_publish_departures_json(hass: HomeAssistant, payload_json: str) -> None:
    """Publish the departures payload to the LED matrix topic."""
    await _async_publish_if_changed(hass, MQTT_DEPARTURES_TOPIC, payload_json, retain=True)


def build_deviations_payload(sorted_deviations: list[Deviation]) -> dict[str, object]:
    """Build the MQTT payload for deviations."""
    deviation_list = [
        {
            "importance_lvl": int(deviation.importance_level),
            "message": deviation.message,
        }
        for deviation in sorted_deviations
    ]
    return {
        "noof_deviations": len(deviation_list),
        "deviations": deviation_list,
    }


def build_deviations_payload_json(sorted_deviations: list[Deviation]) -> str:
    """Build the serialized MQTT payload for deviations."""
    return json.dumps(build_deviations_payload(sorted_deviations), ensure_ascii=False)


async def async_publish_deviations_json(hass: HomeAssistant, payload_json: str) -> None:
    """Publish deviations payload to the deviations topic."""
    await _async_publish_if_changed(hass, MQTT_DEVIATIONS_TOPIC, payload_json, retain=True)


async def async_publish_light_control_state(hass: HomeAssistant, is_on: bool, brightness: int) -> None:
    """Publish metro sign light power and brightness to one state topic."""
    state_value = 1 if is_on else 0
    brightness_value = max(0, min(255, int(brightness))) if is_on else 0
    payload = {
        "power": state_value,
        "brightness": brightness_value,
    }

    await _async_publish_if_changed(hass, MQTT_STATE_TOPIC, json.dumps(payload), retain=True)
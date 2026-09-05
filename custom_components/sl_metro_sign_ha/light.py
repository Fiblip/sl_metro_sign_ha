"""Light platform for metro sign display control."""

from __future__ import annotations

import logging

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import _get_global_display_brightness_limits, async_set_display_enabled
from .mqtt_builder import async_publish_light_control_state

_LOGGER = logging.getLogger(__name__)


def _percent_to_brightness(percent: int) -> int:
    """Convert a 1-100 percent value to the Home Assistant 1-255 brightness scale."""
    return max(1, min(255, round(percent * 255 / 100)))


def _brightness_limits_from_percent(minimum_percent: int, maximum_percent: int) -> tuple[int, int]:
    """Convert percent brightness limits to the Home Assistant scale."""
    minimum_brightness = _percent_to_brightness(minimum_percent)
    maximum_brightness = _percent_to_brightness(maximum_percent)
    return minimum_brightness, max(minimum_brightness, maximum_brightness)


def _clamp_brightness(value: int, minimum: int, maximum: int) -> int:
    """Clamp a brightness value to the configured range."""
    return max(minimum, min(maximum, value))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the display light for a global SL Metro Sign config entry."""
    async_add_entities([MetroSignLight(entry)])


class MetroSignLight(LightEntity, RestoreEntity):
    """Minimal light entity used to control the metro sign display state."""

    _attr_has_entity_name = True
    _attr_name = "SL Metro Sign Display"
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_display"
        self._attr_device_info = {
            "identifiers": {(entry.domain, entry.entry_id)},
            "name": "SL Metro Sign Display",
            "manufacturer": "Fiblip",
            "model": "LED Matrix HUB75 P4 Display",
        }
        self._is_on = False
        self._brightness = 0

    @property
    def is_on(self) -> bool:
        """Return whether the light is on."""
        return self._is_on

    @property
    def brightness(self) -> int:
        """Return brightness in Home Assistant 0-255 scale."""
        return self._brightness

    async def async_added_to_hass(self) -> None:
        """Restore the last known light state and align polling with it."""
        await super().async_added_to_hass()

        minimum_percent, maximum_percent = _get_global_display_brightness_limits(self.hass)
        minimum_brightness, maximum_brightness = _brightness_limits_from_percent(minimum_percent, maximum_percent)

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
            restored_brightness = last_state.attributes.get(ATTR_BRIGHTNESS)
            if restored_brightness is not None:
                self._brightness = _clamp_brightness(int(restored_brightness), minimum_brightness, maximum_brightness)

        if self._is_on and self._brightness <= 0:
            self._brightness = maximum_brightness

        if self._brightness > 0:
            self._brightness = _clamp_brightness(self._brightness, minimum_brightness, maximum_brightness)

        await async_set_display_enabled(self.hass, self._is_on, refresh_immediately=self._is_on)
        await self._async_publish_control_state()
        self.async_write_ha_state()

    async def _async_publish_control_state(self) -> None:
        """Publish current power and brightness values to MQTT."""
        try:
            await async_publish_light_control_state(self.hass, self._is_on, self._brightness)
        except Exception:
            _LOGGER.exception("Failed to publish metro sign light control state to MQTT.")

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the display light on and optionally update brightness."""
        was_on = self._is_on
        minimum_percent, maximum_percent = _get_global_display_brightness_limits(self.hass)
        minimum_brightness, maximum_brightness = _brightness_limits_from_percent(minimum_percent, maximum_percent)

        self._is_on = True
        if ATTR_BRIGHTNESS in kwargs:
            value = int(kwargs[ATTR_BRIGHTNESS])
            self._brightness = _clamp_brightness(value, minimum_brightness, maximum_brightness)
        else:
            current_brightness = self._brightness if self._brightness > 0 else maximum_brightness
            self._brightness = _clamp_brightness(current_brightness, minimum_brightness, maximum_brightness)

        await async_set_display_enabled(self.hass, True, refresh_immediately=not was_on)
        await self._async_publish_control_state()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the display light off."""
        self._is_on = False

        await async_set_display_enabled(self.hass, False)
        await self._async_publish_control_state()
        self.async_write_ha_state()

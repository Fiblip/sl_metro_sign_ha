# SL Metro Sign

Custom Home Assistant integration for publishing SL metro departure and deviation data for use with an MQTT-driven metro sign.

## Features

- Select up to 5 metro stations to track departures and deviations with the SL Transport API
- Sorts the departure data and deviations in decending order
- Select priority departures to always be published over MQTT
- Publishes sorted data from selected departures over MQTT

## Installation with HACS

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository.
3. Select the repository category `Integration`.
4. Install `SL Metro Sign`.
5. Restart Home Assistant.

## Configuration

Add the integration from the Home Assistant UI:

1. Go to `Settings` -> `Devices & services`.
2. Select `Add integration`.
3. Search for `SL Metro Sign`.
4. Follow the config flow steps.

## Requirements

- Home Assistant with MQTT configured
- Access to the SL API used by this integration (no API key is needed)

## Repository Layout

The integration code is stored in `custom_components/sl_metro_sign_ha`.

## Status

The manifest now points to the repository documentation and issue tracker.
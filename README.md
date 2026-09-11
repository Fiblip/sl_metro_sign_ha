# SL Metro Sign

Custom Home Assistant integration that fetches SL departures/deviations and publishes curated payloads over MQTT for an LED metro sign.

## What This Integration Does

- Fetches station departures from the SL Transport API.
- Supports these transport modes in station setup:
	- METRO
	- BUS
	- TRAM
	- TRAIN
	- FERRY
	- SHIP
	- TAXI
- Lets you configure multiple station entries and merges/sorts departures across them.
- Publishes departures and deviations to dedicated MQTT topics.
- Exposes a light entity for display power and brightness control.

## Current Feature Set

- Global settings entry:
	- Forecast hours (1-20)
	- Scan interval seconds
	- Departures: maximum sorted departures (1-10)
	- Departures: optional priority sorting, with 1-3 minimum priority departures
	- Deviations: enabled/disabled
	- Deviations: maximum deviations (0-5)
	- Deviations: minimum importance (1-100)
- Station entries:
	- Station search and selection
	- Transport, line, and direction selection
- Active station entry cap:
	- Maximum 5 active station entries at once
	- Disabled station entries do not count toward the active cap
	- Disabled station entries are excluded from priority station selection
	- If enabling a station would exceed 5 active entries, it is kept disabled and a warning is raised in Repairs
- Priority safety behavior:
	- If the currently selected priority station entry is disabled or removed, global priority is automatically reset
	- `minimum_priority_entries` is automatically set to `0`
- Station-name matching improvements:
	- Search matching is separator-insensitive (for example `Tcentralen` matches `T-centralen`)
- Config-flow diagnostics:
	- Failed departure fetches in config flow are logged with site, transport, line, and forecast context
- Line filtering:
	- Numeric prefixes are used for the SL API request, then departures are filtered again for an exact line match
	- This keeps line designations such as `43` and `43X` separate

## Sorting Behavior

### Departures

- Primary sort: departure timestamp ascending.
- Secondary sort for equal timestamps:
	- `Nu`
	- `X min`
	- `HH:MM`
- Priority enforcement:
	- Ensures `minimum_priority_entries` from the selected priority station when available.
	- Replaces least-important non-priority rows in the selected window as needed.

### Deviations

- De-duplicates by message text.
- Keeps the highest importance level for duplicate messages.
- Filters by minimum importance.
- Sorts descending by importance.
- Publishes up to configured maximum.

## MQTT Topics And Payloads

- Departures topic: `metro_sign/departures`
- Deviations topic: `metro_sign/deviations`
- Display control state topic: `metro_sign/state`

### Departures payload shape

```json
{
	"noof_deps": 3,
	"dep_info_list": [
		{
			"dep_name": "Fruangen",
			"dep_num": 14,
			"dep_time": "3 min"
		}
	]
}
```

### Deviations payload shape

```json
{
	"noof_deviations": 1,
	"deviations": [
		{
			"importance_lvl": 3,
			"message": "Signal fault"
		}
	]
}
```

### Display state payload shape

```json
{
	"power": 1,
	"brightness": 180
}
```

Notes:
- MQTT publishes are retained.
- Payloads are only republished when content changes.

## Light Entity

- Entity type: Home Assistant light with brightness mode.
- Power state controls whether station refresh/publish loop is active.
- Brightness range: 0-255 state reporting, 1-255 for turn-on brightness values.
- Last known state is restored on Home Assistant restart.

## Installation (HACS)

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository.
3. Set category to `Integration`.
4. Install `SL Metro Sign`.
5. Restart Home Assistant.

## Setup In Home Assistant

1. Go to `Settings` -> `Devices & services`.
2. Select `Add integration`.
3. Search for `SL Metro Sign`.
4. Complete the API, departures, and deviations settings.
5. Add one or more station entries by searching for a station, then selecting its transport, line, and destination.
6. To change global settings later, open the integration's options and select the relevant settings section.

## Requirements

- Home Assistant with MQTT integration configured.
- Network access to `https://transport.integration.sl.se`.
- The SL API forecast window is configured in hours; the integration sends the corresponding value in minutes.

## Troubleshooting

- `no_line_found` during setup:
	- Check Home Assistant logs for config-flow fetch warnings.
	- Verify selected station/transport currently has departures.
- Station search misses punctuation variants:
	- Separator-insensitive matching is supported, but exact names can still help with ambiguous results.
- Cannot enable a station entry:
	- If 5 station entries are already active, disable one first.
	- See Repairs warning in Home Assistant for details.
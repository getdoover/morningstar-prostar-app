# Morningstar ProStar App

A Doover device application that monitors a **Morningstar ProStar** series solar
charge controller (e.g. the ProStar PS-30) over RS485/Modbus and publishes its
battery, solar-panel and load metrics to the Doover platform.

The app polls the controller's holding registers every 5 seconds, decodes the
IEEE half-precision float values, derives battery state of charge, and updates
tags that drive the UI and are logged as trends.

## How it connects

This app does **not** talk to the serial port directly. It reads registers
through the shared **`modbus_interface`** app (declared in `depends_on`), which
owns the physical RS485 bus. The `modbus_config` block in this app's config
tells the modbus interface which bus to open (serial port, baud, etc.) and gives
that bus a **name**; this app then reads from the bus by that name.

Registers are read with `register_type=4` (holding registers, Modbus function
code 03). The controller reports live measurements as half-precision floats, one
per register.

### Dual-controller (Foamer) skids — important

On skids with **two ProStar controllers** (the J5246 Foamer skids run one
ProStar on `SERA` and a second on `SERB`), you deploy **two instances** of this
app. Each instance shares the one `modbus_interface`, so **each instance must be
given a distinct `modbus_config` bus `name` and a distinct `serial_port`**. If
two instances use the same bus name they collide in the shared modbus
interface's bus registry — the second bus definition overwrites the first and
one controller stops being read. Give each instance its own name, for example
`prostar_a` on `/dev/ttySERA` and `prostar_b` on `/dev/ttySERB`, and set the
matching `modbus_slave_id` for each controller.

DeFoamer skids have a single ProStar and therefore a single app instance.

## Configuration

| Key (JSON) | Display name | Type | Notes |
|---|---|---|---|
| `system_voltage` | System Voltage | enum `12` / `24` / `48` | Nominal bank voltage. Default `24`. Sets the battery-voltage / SOC anchors. |
| `battery_max_ah` | Battery Max (Ah) | number (required) | Rated bank capacity; used to derive remaining Ah and the Ah gauge ranges. |
| `modbus_slave_id` | Modbus Slave ID | integer (required) | Modbus unit ID of the ProStar on its bus. |
| `modbus_config` | Modbus Config | object (required) | Bus definition passed to the shared modbus interface. Set a **distinct `name` + `serial_port`** per instance (see above). |

### Deployed-config key migration

The legacy (0.4-era) schema keyed the capacity field as **`battery_max_(ah)`**
(with parentheses). pydoover 1.9.1's config key validator no longer permits
parentheses, so the key is now **`battery_max_ah`**. Any instance that was
deployed with the old key must have its config updated to the new key —
otherwise the required value won't load and the app will error on startup. The
`system_voltage`, `modbus_slave_id` and `modbus_config` keys are unchanged.

## Published tags

| Tag | Meaning | Units |
|---|---|---|
| `b_voltage` | Battery terminal voltage | V |
| `b_percent` | Battery state of charge | % |
| `remaining_ah` | Estimated remaining capacity | Ah |
| `panel_voltage` | Solar array voltage | V |
| `panel_current` | Solar array current | A |
| `panel_power` | Solar array power (V × A) | W |
| `load_current` | Load current | A |
| `daily_load` | Load amp-hours today | Ah |
| `daily_charge` | Charge amp-hours today | Ah |
| `comms_ok` | `True` while the controller is being polled successfully | boolean |

Battery state of charge interpolates linearly between the empty (~0%) and full
(~100%) terminal voltages for the configured system voltage and is clamped to
0–100%. When a poll fails, `comms_ok` is set `False` (which shows the "No
communication with solar controller" warning in the UI) and the metric tags are
left at their last value rather than being cleared.

## Development

Install dependencies and run the tests:

```bash
uv sync --all-extras --dev
uv run pytest tests/
```

Regenerate the config and UI schema blocks in `doover_config.json` after
changing `app_config.py` / `app_ui.py`:

```bash
uv run export-config
uv run export-ui
```

Run the application locally:

```bash
doover app run
```

## Simulators

`simulators/app_config.json` holds a sample deployment config (single ProStar,
24 V, 230 Ah) using the sanitised schema keys. `simulators/docker-compose.yml`
positions the app alongside a device agent.

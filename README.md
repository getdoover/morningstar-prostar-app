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

## Field comms check

`scripts/check_comms.py` answers one question — is this controller talking? It
reads a single holding register (battery voltage, 24) over Modbus RTU or Modbus
TCP and reports the verdict in its exit code, so an agent or a script can run it
unattended. **Standard library only** — no pymodbus, no pyserial, nothing to
install on the target:

```bash
python3 scripts/check_comms.py --port /dev/ttyUSB0 --slave 1
python3 scripts/check_comms.py --host 192.168.1.50 --slave 1 --json
```

| exit | meaning |
|---|---|
| 0 | comms OK, plausible reading returned |
| 1 | no or bad response, or a response too implausible to trust |
| 2 | bad arguments |

`--json` emits one object (including the raw register and the hex frame) for
programmatic use. Note the app must be stopped first if it holds the serial port
— only one process can own an RS485 tty at a time.

`scripts/read_registers.py` is the fuller bench tool: decodes every register in
the app's map plus the derived figures, `--watch N` to poll, and `--dump S E` to
dump a raw range with half-float / int interpretations side by side when you
suspect the register map. It needs pymodbus, so run it as
`uv run --with pymodbus scripts/read_registers.py ...`.

### Acceptance test

`scripts/test_prostar.py` is the one to reach for when commissioning or after
re-cabling. Standard library only, and it shares the app's own register map so
the test cannot drift from what production reads. Seven checks — port
contention, port opens, comms, full block read, value plausibility, derived
values, and stability over N reads — each PASS/FAIL, with the verdict in the
exit code:

```bash
# Baseline on a known-good USB-RS485 dongle
python3 scripts/test_prostar.py --port /dev/ttyUSB0 --save-baseline /tmp/prostar.json

# Re-cable to the doovit's own port, then verify against that baseline
sudo python3 scripts/test_prostar.py --port /dev/ttyAMA0 --compare /tmp/prostar.json
```

Two gotchas it exists to catch. **Port contention**: on a doovit the
`modbus_interface` container owns `/dev/ttyAMA0`, and two masters on one RS485
bus corrupt each other's frames — the test names the holding process instead of
failing mysteriously. Run it with `sudo`, or it cannot see other processes'
descriptors and will wrongly report the port free. **Hardware flow control**:
`tty.setraw()` does not clear `CRTSCTS`, and a USB-RS485 dongle never asserts
CTS, so leaving it set stalls writes — indistinguishable from dead wiring.

Note these scripts talk to the serial port directly, bypassing the
`modbus_interface`. A pass proves the wiring, framing and controller are good;
it says nothing about whether the app's deployed `modbus_config` is correct.

## Simulators

`simulators/app_config.json` holds a sample deployment config (single ProStar,
24 V, 230 Ah) using the sanitised schema keys. `simulators/docker-compose.yml`
positions the app alongside a device agent.

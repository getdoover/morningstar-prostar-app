#!/usr/bin/env python3
"""Standalone bench tool: read a Morningstar ProStar's registers directly.

This talks to the controller with pymodbus instead of going through the Doover
modbus interface, so you can sanity-check wiring, baud rate, slave ID and the
register map on a bench or in the field without deploying the app.

It reuses the app's own ``HoldingRegisters`` map and ``decode_float16`` so what
you see here is what the app would publish.

Usage (pymodbus is not an app dependency, so pull it in ad hoc):

    # RS485 serial, slave ID 1
    uv run --with pymodbus scripts/read_registers.py --port /dev/ttyUSB0 --slave 1

    # Modbus TCP (e.g. against a gateway)
    uv run --with pymodbus scripts/read_registers.py --host 192.168.1.50 --slave 1

    # Poll every 2 s until Ctrl-C
    uv run --with pymodbus scripts/read_registers.py --port /dev/ttyUSB0 --watch 2

    # Dump every raw register in a range, all interpretations
    uv run --with pymodbus scripts/read_registers.py --port /dev/ttyUSB0 --dump 0 80
"""

import argparse
import importlib.util
import sys
import time
from pathlib import Path


def _load_app_utils():
    """Load the app's utils module straight from its file.

    Importing ``morningstar_prostar_app.utils`` normally would execute the
    package ``__init__``, which pulls in pydoover -- not necessarily installed on
    a bench machine. Loading the single file by path keeps this script runnable
    with nothing but pymodbus.
    """
    path = Path(__file__).parents[1] / "src" / "morningstar_prostar_app" / "utils.py"
    spec = importlib.util.spec_from_file_location("_prostar_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_utils = _load_app_utils()
HoldingRegisters = _utils.HoldingRegisters
SystemVoltage = _utils.SystemVoltage
decode_float16 = _utils.decode_float16

DEFAULT_BAUD = 9600
DEFAULT_SLAVE = 1
DEFAULT_TCP_PORT = 502


def build_client(args):
    """Return a connected pymodbus client for either serial or TCP transport."""
    try:
        from pymodbus.client import ModbusSerialClient, ModbusTcpClient
    except ImportError:
        sys.exit(
            "pymodbus is not installed. Re-run via:\n"
            "  uv run --with pymodbus scripts/read_registers.py ..."
        )

    if args.host:
        client = ModbusTcpClient(args.host, port=args.tcp_port, timeout=args.timeout)
        target = f"tcp://{args.host}:{args.tcp_port}"
    else:
        client = ModbusSerialClient(
            port=args.port,
            baudrate=args.baud,
            bytesize=8,
            parity="N",
            stopbits=2,  # ProStar RS485 default is 8-N-2
            timeout=args.timeout,
        )
        target = f"{args.port} @ {args.baud} 8-N-2"

    if not client.connect():
        sys.exit(f"Could not open {target}")
    return client, target


def read_block(client, start, count, slave):
    """Read holding registers, tolerating pymodbus's slave/unit/device_id churn.

    The unit-id kwarg was ``unit`` in pymodbus 2.x, ``slave`` in 3.0-3.8 and
    ``device_id`` in 3.9+. Try each rather than pinning a version.
    """
    last_error = None
    for kwarg in ("device_id", "slave", "unit"):
        try:
            rr = client.read_holding_registers(start, count=count, **{kwarg: slave})
        except TypeError as e:
            last_error = e
            continue
        if rr.isError():
            raise RuntimeError(f"Modbus error reading {count} regs at {start}: {rr}")
        return list(rr.registers)
    raise RuntimeError(f"pymodbus API mismatch, no working unit-id kwarg: {last_error}")


def read_named(client, slave):
    """Read the block the app reads and decode the named registers from it."""
    start = HoldingRegisters.start_address()
    count = HoldingRegisters.register_count()
    registers = read_block(client, start, count, slave)
    if len(registers) < count:
        raise RuntimeError(
            f"Short read: wanted {count} registers, got {len(registers)}"
        )
    return {reg: decode_float16(registers[reg.index]) for reg in HoldingRegisters}


def derived(values, system_voltage, capacity_ah):
    """The same derived figures application._process_state() computes."""
    b_voltage = values[HoldingRegisters.BATTERY_VOLTAGE]
    panel_v = values[HoldingRegisters.PANEL_VOLTAGE]
    panel_i = values[HoldingRegisters.PANEL_CURRENT]

    sv = SystemVoltage(system_voltage)
    b_percent = sv.get_battery_percentage(b_voltage)
    out = {
        "panel_power (W)": round(panel_v * panel_i, 2),
        "battery (%)": b_percent,
    }
    if capacity_ah is not None and b_percent is not None:
        out["remaining (Ah)"] = round(capacity_ah * (b_percent / 100), 1)
    return out


UNITS = {
    HoldingRegisters.PANEL_CURRENT: "A",
    HoldingRegisters.PANEL_VOLTAGE: "V",
    HoldingRegisters.LOAD_CURRENT: "A",
    HoldingRegisters.BATTERY_VOLTAGE: "V",
    HoldingRegisters.HEAT_SINK_TEMP: "degC",
    HoldingRegisters.DAILY_LOAD: "Ah",
    HoldingRegisters.DAILY_CHARGE: "Ah",
}


def print_named(values, args):
    print(f"{'register':<18}{'addr':>6}{'value':>12}  unit")
    print("-" * 44)
    for reg in sorted(HoldingRegisters, key=lambda r: r.value):
        print(
            f"{reg.name.lower():<18}{reg.value:>6}{values[reg]:>12.3f}"
            f"  {UNITS.get(reg, '')}"
        )
    print()
    for label, val in derived(values, args.system_voltage, args.capacity).items():
        print(f"{label:<18}{'':>6}{val if val is not None else 'n/a':>12}")


def print_dump(client, args):
    """Dump a raw register range with every plausible interpretation.

    Useful when you suspect the map is wrong: the half-float column is what the
    app assumes, and the int columns let you spot registers that are really
    scaled integers or bitfields.
    """
    start, end = args.dump
    count = end - start + 1
    registers = read_block(client, start, count, args.slave)

    named = {reg.value: reg.name.lower() for reg in HoldingRegisters}
    print(f"{'addr':>5}{'raw':>8}{'hex':>8}{'f16':>14}{'int16':>8}  name")
    print("-" * 60)
    for offset, raw in enumerate(registers):
        addr = start + offset
        signed = raw - 65536 if raw > 32767 else raw
        print(
            f"{addr:>5}{raw:>8}{raw:>#8x}{decode_float16(raw):>14.4f}"
            f"{signed:>8}  {named.get(addr, '')}"
        )


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Read a Morningstar ProStar's Modbus registers directly.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    transport = p.add_argument_group("transport (pick serial or TCP)")
    transport.add_argument("--port", help="Serial device, e.g. /dev/ttyUSB0")
    transport.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    transport.add_argument("--host", help="Modbus TCP host (instead of --port)")
    transport.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    transport.add_argument("--timeout", type=float, default=3.0)
    transport.add_argument(
        "--slave", type=int, default=DEFAULT_SLAVE, help="Modbus slave/unit ID"
    )

    p.add_argument(
        "--system-voltage",
        type=int,
        choices=[v.value for v in SystemVoltage],
        default=SystemVoltage.V_24.value,
        help="Nominal bank voltage, for the battery %% calculation",
    )
    p.add_argument(
        "--capacity",
        type=float,
        help="Bank capacity in Ah, to also report remaining Ah",
    )
    p.add_argument(
        "--dump",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Dump this raw register range instead of the named map",
    )
    p.add_argument(
        "--watch",
        type=float,
        metavar="SECONDS",
        help="Re-read on this interval until interrupted",
    )

    args = p.parse_args(argv)
    if bool(args.port) == bool(args.host):
        p.error("give exactly one of --port (serial) or --host (TCP)")
    return args


def main(argv=None):
    args = parse_args(argv)
    client, target = build_client(args)
    print(f"Connected: {target}, slave {args.slave}\n")

    try:
        while True:
            try:
                if args.dump:
                    print_dump(client, args)
                else:
                    print_named(read_named(client, args.slave), args)
            except RuntimeError as e:
                # Keep polling in --watch mode: a dropout shouldn't end the run.
                print(f"read failed: {e}", file=sys.stderr)
                if not args.watch:
                    return 1
            if not args.watch:
                return 0
            time.sleep(args.watch)
            print()
    except KeyboardInterrupt:
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

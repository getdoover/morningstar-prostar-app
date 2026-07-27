#!/usr/bin/env python3
"""End-to-end acceptance test for a Morningstar ProStar over Modbus RTU.

Built for the bench-to-device changeover: prove the controller reads correctly
on a USB-RS485 dongle, then re-run the identical test on the doovit's own serial
port and confirm you get the same answers.

    # 1. Baseline on the USB dongle (known good)
    python3 scripts/test_prostar.py --port /dev/ttyUSB5 --save-baseline /tmp/prostar.json

    # 2. Re-cable to the doovit's port, then verify against that baseline
    python3 scripts/test_prostar.py --port /dev/ttyAMA0 --compare /tmp/prostar.json

Standard library only -- no pymodbus, no pyserial -- so it runs on any doovit
without building a venv. Exit code is the verdict:

    0 -> every check passed
    1 -> at least one check failed
    2 -> bad invocation

Two things this checks that a plain register read does not:

* **Port contention.** On a doovit the ``modbus_interface`` container owns
  ``/dev/ttyAMA0``. Two masters on one RS485 bus corrupt each other's frames, so
  a test run against a port someone else holds fails for reasons that have
  nothing to do with your wiring. This reports the holder before testing.
* **Hardware flow control.** ``tty.setraw()`` does not clear ``CRTSCTS``, and a
  USB-RS485 dongle never asserts CTS -- leaving it set makes writes stall so the
  request never reaches the bus, which looks exactly like dead wiring.
"""

import argparse
import importlib.util
import json
import math
import os
import select
import statistics
import struct
import sys
import termios
import time
import tty
from pathlib import Path

DEFAULT_BAUD = 9600
DEFAULT_SLAVE = 1
DEFAULT_STOPBITS = 2  # Morningstar specs 8-N-2 for Modbus
DEFAULT_TIMEOUT = 3.0
DEFAULT_REPEAT = 5

FUNCTION_READ_HOLDING = 3  # FC03, what the app uses
FUNCTION_READ_INPUT = 4  # FC04, what the legacy 0.4 app used


# ---------------------------------------------------------------------------
# Register map -- shared with the app so the test cannot drift from production
# ---------------------------------------------------------------------------


def _load_app_utils():
    """Load the app's utils module by path, falling back to an embedded copy.

    Importing the package normally would execute its ``__init__`` and pull in
    pydoover, which is not installed on a bench machine. Loading the single file
    keeps the register map and SoC curve identical to what the app publishes.
    The fallback exists so this script still works when copied somewhere on its
    own, away from the repo.
    """
    path = Path(__file__).parents[1] / "src" / "morningstar_prostar_app" / "utils.py"
    if path.exists():
        spec = importlib.util.spec_from_file_location("_prostar_utils", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, str(path)

    import enum

    class _Fallback:
        @staticmethod
        def decode_float16(val):
            if val > 32767:
                val -= 65536
            return struct.unpack("e", struct.pack("h", val))[0]

        class SystemVoltage(enum.Enum):
            V_12, V_24, V_48 = 12, 24, 48

            @property
            def full_voltage(self):
                return self.value * (25.6 / 24)

            @property
            def empty_voltage(self):
                return self.value * (22.0 / 24)

            def get_battery_percentage(self, v):
                if v is None:
                    return None
                span = self.full_voltage - self.empty_voltage
                return round(
                    max(0.0, min(100.0, (v - self.empty_voltage) / span * 100)), 2
                )

        class HoldingRegisters(enum.Enum):
            PANEL_CURRENT, PANEL_VOLTAGE, LOAD_CURRENT = 17, 19, 22
            BATTERY_VOLTAGE, HEAT_SINK_TEMP = 24, 26
            DAILY_CHARGE, DAILY_LOAD = 67, 68

            @classmethod
            def start_address(cls):
                return min(i.value for i in cls)

            @classmethod
            def register_count(cls):
                v = [i.value for i in cls]
                return max(v) - min(v) + 1

            @property
            def index(self):
                return self.value - self.__class__.start_address()

    return _Fallback, "(embedded fallback copy)"


_utils, _utils_source = _load_app_utils()
decode_float16 = _utils.decode_float16
SystemVoltage = _utils.SystemVoltage
HoldingRegisters = _utils.HoldingRegisters

UNITS = {
    "PANEL_CURRENT": "A",
    "PANEL_VOLTAGE": "V",
    "LOAD_CURRENT": "A",
    "BATTERY_VOLTAGE": "V",
    "HEAT_SINK_TEMP": "degC",
    "DAILY_CHARGE": "Ah",
    "DAILY_LOAD": "Ah",
}


def plausible_ranges(system_voltage):
    """Sane operating bounds per register, for the configured bank voltage.

    Deliberately wide: the point is to catch a wrong register map or a bad
    decode (which produce wild numbers, NaN or inf), not to police whether the
    solar system is performing well.
    """
    sv = system_voltage.value
    return {
        "PANEL_CURRENT": (-2.0, 100.0),
        "PANEL_VOLTAGE": (-1.0, sv * 6),
        "LOAD_CURRENT": (-2.0, 100.0),
        "BATTERY_VOLTAGE": (sv * 0.75, sv * 1.45),
        "HEAT_SINK_TEMP": (-40.0, 100.0),
        "DAILY_CHARGE": (0.0, 2000.0),
        "DAILY_LOAD": (0.0, 2000.0),
    }


# ---------------------------------------------------------------------------
# Modbus RTU over a raw serial fd
# ---------------------------------------------------------------------------


class Timeout(Exception):
    pass


class BadResponse(Exception):
    pass


def crc16(data):
    """Modbus RTU CRC-16, returned little-endian as it goes on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def open_serial(port, baud, stopbits):
    speed = getattr(termios, f"B{baud}", None)
    if speed is None:
        raise ValueError(f"unsupported baud rate {baud}")

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        # attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
        attrs[2] = (attrs[2] & ~termios.CSIZE) | termios.CS8  # 8 data bits
        attrs[2] &= ~termios.PARENB  # no parity
        if stopbits == 2:
            attrs[2] |= termios.CSTOPB
        else:
            attrs[2] &= ~termios.CSTOPB
        attrs[2] |= termios.CLOCAL | termios.CREAD
        # See the module docstring: CRTSCTS left set makes writes stall forever
        # on a dongle that never asserts CTS. Software flow control must go too,
        # or 0x11/0x13 bytes inside a Modbus frame get eaten as XON/XOFF.
        attrs[2] &= ~termios.CRTSCTS
        attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
        attrs[4] = attrs[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


def _read_exactly(fd, count, deadline):
    buf = b""
    while len(buf) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Timeout(f"got {len(buf)} of {count} bytes")
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            raise Timeout(f"got {len(buf)} of {count} bytes")
        chunk = os.read(fd, count - len(buf))
        if not chunk:
            raise Timeout("port closed mid-frame")
        buf += chunk
    return buf


def read_registers(fd, slave, start, count, timeout, function=FUNCTION_READ_HOLDING):
    """Read `count` registers from `start`. Returns a list of raw 16-bit ints."""
    termios.tcflush(fd, termios.TCIFLUSH)  # drop stale bytes from a prior timeout
    request = struct.pack(">BBHH", slave, function, start, count)
    os.write(fd, request + crc16(request))

    deadline = time.monotonic() + timeout
    header = _read_exactly(fd, 3, deadline)

    if header[1] & 0x80:
        _read_exactly(fd, 2, deadline)  # drain the CRC so the port stays clean
        raise BadResponse(f"modbus exception code {header[2]}")
    if header[0] != slave or header[1] != function:
        raise BadResponse(f"unexpected header {header.hex()}")

    byte_count = header[2]
    if byte_count != count * 2:
        raise BadResponse(f"expected {count * 2} data bytes, slave said {byte_count}")

    body = _read_exactly(fd, byte_count + 2, deadline)
    data, received_crc = body[:byte_count], body[byte_count:]
    if crc16(header + data) != received_crc:
        raise BadResponse("CRC mismatch (noise, wrong baud, or two masters on the bus)")

    return list(struct.unpack(f">{count}H", data))


def read_named_block(fd, slave, timeout, function):
    """Read the block the app reads and decode every named register from it."""
    start = HoldingRegisters.start_address()
    count = HoldingRegisters.register_count()
    raw = read_registers(fd, slave, start, count, timeout, function)
    return {reg.name: decode_float16(raw[reg.index]) for reg in HoldingRegisters}, raw


# ---------------------------------------------------------------------------
# Port contention
# ---------------------------------------------------------------------------


def port_holders(port):
    """Best-effort list of (pid, cmdline) processes holding `port` open.

    Without root we can only see our own file descriptors, so an empty result is
    not proof the port is free -- hence the note in the report.
    """
    try:
        target = os.path.realpath(port)
    except OSError:
        return [], False
    holders, complete = [], True
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            entries = os.listdir(fd_dir)
        except PermissionError:
            complete = False
            continue
        except OSError:
            continue
        for fd in entries:
            try:
                if os.readlink(os.path.join(fd_dir, fd)) != target:
                    continue
            except OSError:
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = (
                        fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
                    )
            except OSError:
                cmd = "?"
            holders.append((int(pid), cmd or "?"))
            break
    return holders, complete


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class Report:
    def __init__(self):
        self.checks = []

    def add(self, name, passed, detail, skipped=False):
        self.checks.append(
            {"check": name, "passed": passed, "skipped": skipped, "detail": detail}
        )
        return passed

    @property
    def ok(self):
        return all(c["passed"] for c in self.checks if not c["skipped"])

    def render(self):
        width = max(len(c["check"]) for c in self.checks)
        lines = []
        for c in self.checks:
            mark = "SKIP" if c["skipped"] else ("PASS" if c["passed"] else "FAIL")
            lines.append(f"  [{mark}] {c['check']:<{width}}  {c['detail']}")
        return "\n".join(lines)


def run_tests(args, report):
    sv = SystemVoltage(args.system_voltage)
    ranges = plausible_ranges(sv)
    results = {"port": args.port, "slave": args.slave, "values": None, "derived": None}

    # -- 1. contention -------------------------------------------------------
    holders, complete = port_holders(args.port)
    if holders:
        listed = "; ".join(f"pid {p}: {c[:60]}" for p, c in holders)
        report.add(
            "port exclusive",
            False,
            f"another process holds {args.port} -- {listed}. Two masters on one "
            f"RS485 bus corrupt each other's frames; stop it before testing.",
        )
    else:
        note = "" if complete else " (ran unprivileged; re-run with sudo to be sure)"
        report.add("port exclusive", True, f"no other process holds {args.port}{note}")

    # -- 2. port opens -------------------------------------------------------
    try:
        fd = open_serial(args.port, args.baud, args.stopbits)
    except (OSError, ValueError) as e:
        report.add("port opens", False, f"cannot open {args.port} @ {args.baud}: {e}")
        return results
    report.add(
        "port opens",
        True,
        f"{args.port} @ {args.baud} 8-N-{args.stopbits}",
    )

    try:
        # -- 3. single register (comms alive) --------------------------------
        battery_addr = HoldingRegisters.BATTERY_VOLTAGE.value
        try:
            raw = read_registers(
                fd, args.slave, battery_addr, 1, args.timeout, args.function
            )[0]
            volts = decode_float16(raw)
            report.add(
                "comms",
                True,
                f"slave {args.slave} answered: register {battery_addr} = "
                f"{volts:.3f} V (raw 0x{raw:04x})",
            )
        except (Timeout, BadResponse, OSError) as e:
            report.add(
                "comms",
                False,
                f"no valid response from slave {args.slave}: "
                f"{type(e).__name__}: {e}. Check A/B polarity, termination, "
                f"slave ID, controller power.",
            )
            return results

        # -- 4. full block read ----------------------------------------------
        start = HoldingRegisters.start_address()
        count = HoldingRegisters.register_count()
        try:
            values, raw_block = read_named_block(
                fd, args.slave, args.timeout, args.function
            )
            results["values"] = values
            results["raw_block"] = raw_block
            report.add(
                "block read",
                True,
                f"{count} registers from {start} in one transaction",
            )
        except (Timeout, BadResponse, OSError) as e:
            report.add(
                "block read",
                False,
                f"{count}-register read from {start} failed: {type(e).__name__}: {e}",
            )
            return results

        # -- 5. values sane ---------------------------------------------------
        bad = []
        for name, value in values.items():
            low, high = ranges[name]
            if math.isnan(value) or math.isinf(value):
                bad.append(f"{name.lower()}={value} (not a finite number)")
            elif not low <= value <= high:
                bad.append(
                    f"{name.lower()}={value:.3f}{UNITS[name]} outside {low:g}..{high:g}"
                )
        if bad:
            report.add(
                "values sane",
                False,
                "suspect a register-map or decode mismatch -- " + "; ".join(bad),
            )
        else:
            report.add(
                "values sane",
                True,
                f"all {len(values)} registers within plausible range for a "
                f"{sv.value} V system",
            )

        # -- 6. derived --------------------------------------------------------
        battery = values["BATTERY_VOLTAGE"]
        percent = sv.get_battery_percentage(battery)
        derived = {
            "panel_power_w": round(
                values["PANEL_VOLTAGE"] * values["PANEL_CURRENT"], 2
            ),
            "battery_percent": percent,
        }
        if args.capacity:
            derived["remaining_ah"] = round(args.capacity * (percent / 100), 1)
        results["derived"] = derived
        report.add(
            "derived values",
            percent is not None,
            f"panel {derived['panel_power_w']} W, battery {percent}%"
            + (
                f", {derived.get('remaining_ah')} Ah remaining" if args.capacity else ""
            ),
        )

        # -- 7. stability ------------------------------------------------------
        if args.repeat > 1:
            ok_count, errors, samples = 1, [], [battery]
            for _ in range(args.repeat - 1):
                time.sleep(args.interval)
                try:
                    again, _ = read_named_block(
                        fd, args.slave, args.timeout, args.function
                    )
                    samples.append(again["BATTERY_VOLTAGE"])
                    ok_count += 1
                except (Timeout, BadResponse, OSError) as e:
                    errors.append(f"{type(e).__name__}: {e}")
            spread = max(samples) - min(samples)
            results["stability"] = {
                "reads": args.repeat,
                "ok": ok_count,
                "battery_mean": round(statistics.fmean(samples), 3),
                "battery_spread": round(spread, 3),
                "errors": errors,
            }
            detail = (
                f"{ok_count}/{args.repeat} reads OK, battery "
                f"{statistics.fmean(samples):.3f} V +/- {spread / 2:.3f}"
            )
            if errors:
                detail += f" -- {len(errors)} failure(s): {errors[0]}"
            report.add("stability", ok_count == args.repeat, detail)
    finally:
        os.close(fd)

    return results


def compare_baseline(results, baseline, tolerance, report):
    """Check this run against a known-good run taken on another port."""
    base_vals = baseline.get("values") or {}
    now_vals = results.get("values") or {}
    if not base_vals or not now_vals:
        report.add(
            "baseline compare",
            False,
            "no register values to compare",
        )
        return

    missing = sorted(set(base_vals) - set(now_vals))
    if missing:
        report.add("baseline compare", False, f"registers missing now: {missing}")
        return

    base_b, now_b = base_vals["BATTERY_VOLTAGE"], now_vals["BATTERY_VOLTAGE"]
    delta = abs(now_b - base_b)
    report.add(
        "baseline compare",
        delta <= tolerance,
        f"battery {now_b:.3f} V vs baseline {base_b:.3f} V from "
        f"{baseline.get('port', '?')} (delta {delta:.3f} V, tolerance {tolerance} V)",
    )

    # Informational only: currents, temperature and the daily counters all move
    # between runs, so a difference there is not a failure.
    drift = ", ".join(
        f"{n.lower()} {base_vals[n]:.3f}->{now_vals[n]:.3f}{UNITS[n]}"
        for n in sorted(now_vals)
        if abs(now_vals[n] - base_vals[n]) > 1e-6
    )
    if drift:
        print(f"\nLive values that moved since the baseline (expected): {drift}")


def print_values(results):
    values, derived = results.get("values"), results.get("derived")
    if not values:
        return
    print(f"\n{'register':<18}{'addr':>6}{'value':>12}  unit")
    print("-" * 44)
    for reg in sorted(HoldingRegisters, key=lambda r: r.value):
        print(
            f"{reg.name.lower():<18}{reg.value:>6}{values[reg.name]:>12.3f}"
            f"  {UNITS[reg.name]}"
        )
    if derived:
        print()
        for label, val in derived.items():
            print(f"{label:<18}{'':>6}{val if val is not None else 'n/a':>12}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Acceptance-test a Morningstar ProStar over Modbus RTU.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--port", required=True, help="serial device, e.g. /dev/ttyAMA0")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument(
        "--stopbits",
        type=int,
        choices=(1, 2),
        default=DEFAULT_STOPBITS,
        help=f"default {DEFAULT_STOPBITS}, per the Morningstar Modbus spec",
    )
    p.add_argument("--slave", type=int, default=DEFAULT_SLAVE)
    p.add_argument(
        "--function",
        type=int,
        choices=(3, 4),
        default=FUNCTION_READ_HOLDING,
        help="3 = holding registers (what the app uses), 4 = input registers",
    )
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument(
        "--system-voltage",
        type=int,
        choices=[v.value for v in SystemVoltage],
        default=SystemVoltage.V_24.value,
        help="nominal bank voltage",
    )
    p.add_argument("--capacity", type=float, help="bank capacity in Ah")
    p.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        help=f"consecutive reads for the stability check (default {DEFAULT_REPEAT})",
    )
    p.add_argument("--interval", type=float, default=0.5)
    p.add_argument("--save-baseline", metavar="FILE", help="write results as JSON")
    p.add_argument("--compare", metavar="FILE", help="compare against a saved baseline")
    p.add_argument(
        "--tolerance",
        type=float,
        default=2.0,
        help="allowed battery-voltage delta vs baseline, volts (default 2.0)",
    )
    p.add_argument("--json", action="store_true", help="emit one JSON object")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    report = Report()

    if not args.json:
        print(f"ProStar acceptance test -- {args.port}")
        print(f"register map: {_utils_source}\n")

    results = run_tests(args, report)

    if args.compare:
        try:
            with open(args.compare) as fh:
                baseline = json.load(fh)
        except (OSError, ValueError) as e:
            report.add("baseline compare", False, f"cannot read {args.compare}: {e}")
        else:
            compare_baseline(results, baseline, args.tolerance, report)

    if args.save_baseline:
        try:
            with open(args.save_baseline, "w") as fh:
                json.dump(results, fh, indent=2)
        except OSError as e:
            print(f"warning: could not write baseline: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps({"ok": report.ok, "checks": report.checks, **results}))
        return 0 if report.ok else 1

    print(report.render())
    print_values(results)
    print("\n" + ("RESULT: PASS" if report.ok else "RESULT: FAIL"))
    if args.save_baseline:
        print(f"baseline written to {args.save_baseline}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

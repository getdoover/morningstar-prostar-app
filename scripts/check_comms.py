#!/usr/bin/env python3
"""Validate Modbus comms to a Morningstar ProStar. One register, clear verdict.

Built to be run unattended by an agent in the field: standard library only (no
pymodbus, no pyserial), single file, and the answer is in the exit code.

    exit 0  -> comms OK, a plausible reading came back
    exit 1  -> no/!bad response (wiring, baud, slave ID, or controller down)
    exit 2  -> bad invocation (arguments)

Serial runs at 9600 baud, the ProStar's fixed Modbus rate. Reads one holding
register over Modbus RTU (serial) or Modbus TCP -- by default
battery voltage, register 24, which the app also reads. The value is a
half-precision float, decoded the same way the app decodes it.

Examples:

    python3 scripts/check_comms.py --port /dev/ttyUSB0 --slave 1
    python3 scripts/check_comms.py --port /dev/ttyS2 --slave 1 --json
    python3 scripts/check_comms.py --host 192.168.1.50 --slave 1
    python3 scripts/check_comms.py --port /dev/ttyUSB0 --register 19   # panel voltage
"""

import argparse
import json
import os
import select
import socket
import struct
import subprocess
import sys
import time

BATTERY_VOLTAGE_REGISTER = 24  # HoldingRegisters.BATTERY_VOLTAGE in the app

# The ProStar aliases its holding-register and input-register address spaces, so
# the same measurement is readable with either function code. The rewritten app
# reads holding registers (FC03); the legacy 0.4 app read input registers (FC04).
# Default to FC03 but keep FC04 testable -- if one works and the other doesn't,
# that alone explains an app that reads nothing while the wiring is fine.
FUNCTION_READ_HOLDING = 3
FUNCTION_READ_INPUT = 4
FUNCTION_NAMES = {
    FUNCTION_READ_HOLDING: "holding (FC03)",
    FUNCTION_READ_INPUT: "input (FC04)",
}
# The ProStar's Modbus port runs at 9600 baud -- fixed, not a tunable. The
# Doover modbus interface opens these buses at 9600 too.
BAUD = 9600
DEFAULT_SLAVE = 1
DEFAULT_TCP_PORT = 502
DEFAULT_TIMEOUT = 3.0
DEFAULT_ATTEMPTS = 3

# A live 12/24/48 V bank sits well inside this range. Outside it, the number is
# almost certainly a decode/register-map mismatch rather than a real reading, so
# report the bytes but do not claim comms are healthy.
PLAUSIBLE_VOLTAGE = (8.0, 65.0)


def decode_float16(val):
    """Decode one 16-bit register as an IEEE-754 half float (as the app does)."""
    if val > 32767:
        val -= 65536
    return struct.unpack("e", struct.pack("h", val))[0]


def crc16(data):
    """Modbus RTU CRC-16, returned little-endian as it goes on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)


class Timeout(Exception):
    pass


class BadResponse(Exception):
    pass


# --------------------------------------------------------------------------
# Doovit RS485 transceiver -- must be programmed before the port is usable
# --------------------------------------------------------------------------

# On a doovit, /dev/ttyAMA0 runs through an RS485 transceiver managed by the
# doovitd daemon. termios can set the UART's framing but not the transceiver's
# mode, terminator resistor or A/B polarity, so an unconfigured transceiver
# times out identically to dead wiring. `dvt set_serial_params` programs it:
#   baudrate rs485_mode terminator_resistor bits parity stop
#   timeout_ms read_chunk_timeout_ms invert_ab
DVT_RESPONSE_TIMEOUT_MS = 300
DVT_READ_CHUNK_TIMEOUT_MS = 50


def dvt_serial_command(baud, stopbits):
    return [
        "dvt",
        "set_serial_params",
        str(baud),
        "True",  # rs485_mode
        "True",  # terminator_resistor
        "8",  # data bits
        "N",  # parity
        str(stopbits),
        str(DVT_RESPONSE_TIMEOUT_MS),
        str(DVT_READ_CHUNK_TIMEOUT_MS),
        "True",  # invert_ab
    ]


def configure_transceiver(port, baud, stopbits):
    """Program the doovit's RS485 transceiver via dvt before opening the port.

    Returns (status, detail): status is "ok", "skipped" or "failed". Only the
    doovit's own UART (ttyAMA*) goes through the transceiver -- USB dongles and
    bench machines are skipped, and a missing dvt binary means this isn't a
    doovit, which is fine.
    """
    if "ttyAMA" not in os.path.basename(port):
        return "skipped", f"{port} is not the doovit's own UART"
    cmd = dvt_serial_command(baud, stopbits)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False
        )
    except FileNotFoundError:
        return "skipped", "dvt not on PATH (not a doovit?)"
    except subprocess.TimeoutExpired:
        return "failed", f"{' '.join(cmd)} timed out after 15 s"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        return "failed", f"{' '.join(cmd)} exited {proc.returncode}: {err}"
    return "ok", " ".join(cmd)


# --------------------------------------------------------------------------
# Serial (Modbus RTU) -- configured with termios so pyserial isn't needed
# --------------------------------------------------------------------------


def open_serial(port, stopbits=2):
    import termios
    import tty

    speed = getattr(termios, f"B{BAUD}")

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    # attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    attrs[2] = (attrs[2] & ~termios.CSIZE) | termios.CS8  # 8 data bits
    attrs[2] &= ~termios.PARENB  # no parity
    # Morningstar specs 8-N-2 for Modbus, but the Doover modbus interface opens
    # these buses 8N1 -- keep both reachable so framing can be ruled out.
    if stopbits == 2:
        attrs[2] |= termios.CSTOPB
    else:
        attrs[2] &= ~termios.CSTOPB
    attrs[2] |= termios.CLOCAL | termios.CREAD
    # Hardware flow control must be off. tty.setraw() does NOT clear CRTSCTS, and
    # a USB-RS485 dongle never asserts CTS -- leaving it set makes os.write()
    # stall forever, so the request never reaches the bus and every read times
    # out looking exactly like dead wiring. Same for software flow control:
    # 0x11/0x13 bytes in a Modbus frame would otherwise be eaten as XON/XOFF.
    attrs[2] &= ~termios.CRTSCTS
    attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
    attrs[4] = speed
    attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def read_exactly(fd, count, deadline):
    """Read exactly count bytes from fd before deadline, or raise Timeout."""
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


def rtu_read_register(fd, slave, register, timeout, function=FUNCTION_READ_HOLDING):
    request = struct.pack(">BBHH", slave, function, register, 1)
    request += crc16(request)
    os.write(fd, request)

    deadline = time.monotonic() + timeout
    header = read_exactly(fd, 3, deadline)

    if header[1] & 0x80:
        # Exception frame is slave, fc|0x80, code, crc(2) -- the code is already
        # in header[2]; drain the trailing CRC so the port is left clean.
        read_exactly(fd, 2, deadline)
        raise BadResponse(f"modbus exception code {header[2]}")

    if header[0] != slave or header[1] != function:
        raise BadResponse(f"unexpected header {header.hex()}")

    byte_count = header[2]
    if byte_count != 2:
        raise BadResponse(f"expected 2 data bytes, slave said {byte_count}")

    body = read_exactly(fd, byte_count + 2, deadline)  # data + CRC
    frame, received_crc = header + body[:byte_count], body[byte_count:]
    if crc16(frame) != received_crc:
        raise BadResponse("CRC mismatch (noise, wrong baud, or bus contention)")

    return struct.unpack(">H", body[:2])[0], (frame + received_crc)


# --------------------------------------------------------------------------
# Modbus TCP
# --------------------------------------------------------------------------


def tcp_read_register(
    host, port, slave, register, timeout, function=FUNCTION_READ_HOLDING
):
    pdu = struct.pack(">BHH", function, register, 1)
    frame = struct.pack(">HHHB", 1, 0, len(pdu) + 1, slave) + pdu

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(frame)

        def recv(n):
            buf = b""
            while len(buf) < n:
                try:
                    chunk = sock.recv(n - len(buf))
                except TimeoutError as e:
                    raise Timeout(f"got {len(buf)} of {n} bytes") from e
                if not chunk:
                    raise Timeout("connection closed mid-frame")
                buf += chunk
            return buf

        header = recv(8)  # MBAP (7) + function code (1)
        got = header[7]
        if got & 0x80:
            code = recv(1)[0]
            raise BadResponse(f"modbus exception code {code}")
        if got != function:
            raise BadResponse(f"unexpected function code {got}")

        byte_count = recv(1)[0]
        if byte_count != 2:
            raise BadResponse(f"expected 2 data bytes, slave said {byte_count}")
        data = recv(2)
        return struct.unpack(">H", data)[0], header + bytes([byte_count]) + data


# --------------------------------------------------------------------------


def attempt_read(args):
    """One read attempt. Returns (raw_register_value, raw_frame_bytes)."""
    if args.host:
        return tcp_read_register(
            args.host,
            args.tcp_port,
            args.slave,
            args.register,
            args.timeout,
            args.function,
        )
    fd = open_serial(args.port, args.stopbits)
    try:
        return rtu_read_register(
            fd, args.slave, args.register, args.timeout, args.function
        )
    finally:
        os.close(fd)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Validate Modbus comms to a ProStar by reading one register.",
    )
    p.add_argument("--port", help="serial device, e.g. /dev/ttyUSB0")
    p.add_argument(
        "--stopbits",
        type=int,
        choices=(1, 2),
        default=2,
        help="serial stop bits (default 2, per the Morningstar Modbus spec)",
    )
    p.add_argument("--host", help="Modbus TCP host (use instead of --port)")
    p.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    p.add_argument("--slave", type=int, default=DEFAULT_SLAVE, help="Modbus slave ID")
    p.add_argument(
        "--function",
        type=int,
        choices=(FUNCTION_READ_HOLDING, FUNCTION_READ_INPUT),
        default=FUNCTION_READ_HOLDING,
        help="3 = read holding registers (what the app uses), 4 = read input registers",
    )
    p.add_argument(
        "--register",
        type=int,
        default=BATTERY_VOLTAGE_REGISTER,
        help=f"holding register to read (default {BATTERY_VOLTAGE_REGISTER}, battery voltage)",
    )
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument(
        "--no-dvt",
        action="store_true",
        help="skip programming the doovit RS485 transceiver (dvt set_serial_params)",
    )
    p.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help=f"retries before declaring failure (default {DEFAULT_ATTEMPTS})",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="treat the register as an integer, not a half float (skips the plausibility check)",
    )
    p.add_argument("--json", action="store_true", help="emit one JSON object")

    args = p.parse_args(argv)
    if bool(args.port) == bool(args.host):
        p.error("give exactly one of --port (serial) or --host (TCP)")
    return args


def main(argv=None):
    args = parse_args(argv)
    target = args.host or args.port

    if args.port and not args.no_dvt:
        status, detail = configure_transceiver(args.port, BAUD, args.stopbits)
        # stderr so --json keeps stdout to the single result object
        print(f"transceiver {status}: {detail}", file=sys.stderr)

    errors = []
    for attempt in range(1, args.attempts + 1):
        try:
            raw, frame = attempt_read(args)
            break
        except (Timeout, BadResponse, OSError) as e:
            errors.append(f"attempt {attempt}: {type(e).__name__}: {e}")
            if attempt < args.attempts:
                time.sleep(0.5)
    else:
        result = {
            "comms_ok": False,
            "target": target,
            "slave": args.slave,
            "register": args.register,
            "attempts": args.attempts,
            "errors": errors,
        }
        if args.json:
            print(json.dumps(result))
        else:
            print(f"COMMS FAIL: no valid response from {target} (slave {args.slave})")
            for line in errors:
                print(f"  {line}")
            print(
                "\nCheck, in order: RS485 A/B polarity and termination, "
                "slave ID, controller power."
            )
        return 1

    value = raw if args.raw else round(decode_float16(raw), 3)
    plausible = True
    note = ""
    if not args.raw and args.register == BATTERY_VOLTAGE_REGISTER:
        low, high = PLAUSIBLE_VOLTAGE
        plausible = low <= value <= high
        if not plausible:
            note = (
                f"responded, but {value} V is outside the plausible range "
                f"{low}-{high} V -- suspect a register-map or decode mismatch"
            )

    result = {
        "comms_ok": plausible,
        "target": target,
        "slave": args.slave,
        "register": args.register,
        "function": FUNCTION_NAMES[args.function],
        "raw": raw,
        "value": value,
        "attempts_used": attempt,
        "frame": frame.hex(),
    }
    if note:
        result["note"] = note

    if args.json:
        print(json.dumps(result))
    elif plausible:
        unit = ""
        if not args.raw and args.register == BATTERY_VOLTAGE_REGISTER:
            unit = " V"
        print(f"COMMS OK: {target} slave {args.slave} register {args.register}")
        print(f"  value = {value}{unit}  (raw 0x{raw:04x}, {attempt} attempt(s))")
    else:
        print(f"COMMS SUSPECT: {target} slave {args.slave} register {args.register}")
        print(f"  {note}")
        print(f"  raw 0x{raw:04x}, frame {frame.hex()}")

    return 0 if plausible else 1


if __name__ == "__main__":
    sys.exit(main())
